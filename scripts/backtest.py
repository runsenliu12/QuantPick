"""回测：用与生产一致的多因子 composite 做横截面选股，含真实交易约束与组合优化。

说明：
- 这是"策略是否有效"的验证，不是实盘。它尽量复用 selection.score_universe，保证回测对象=实盘模型。
- 因子在每期调仓日"时点化"计算（只用当时可得数据），避免未来函数。
- 收益按**完整日度**持有计算（买入持有到下一调仓日），不再只用调仓当日涨跌。
- 交易约束（A1）：建仓日涨停买不到、平仓日跌停卖不出、停牌顺延，均建模进回测。
- 组合优化（A3）：权重用风险平价（∝1/波动率）而非近等权。
- 换手控制（A2）：相邻调仓期限制被替换标的数量，降低摩擦成本。
- 市场状态缩放（regime）：每个调仓日按指数 vs MA 决定仓位缩放，熊市留现金
  （权重和<1），使回测不再"永远满仓"，与 finalize 实盘口径一致。
- 含交易成本 + 基准(沪深300) + Sharpe/最大回撤/换手/IC，并做前后段(样本内/外)对比。

用法：
    python scripts/backtest.py --pool 80 --lookback 60 --top 10 --rebalance 21
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from src.config import load_config, get
from src.selection import score_universe
from src.data import DataFetcher
from src.risk import portfolio_weights, regime_scale
from src.trading import is_limit_up, is_limit_down


# ---------------- 纯函数：组合模拟与指标（便于单测） ----------------

def simulate_portfolio(ret_matrix: pd.DataFrame, weight_panel: pd.DataFrame,
                       limit_matrix: pd.DataFrame | None, cost: float,
                       cfg: dict | None = None) -> pd.Series:
    """逐日模拟组合净值。

    weight_panel: 日度×标的，每个交易日的目标权重（调仓日变化，其余 forward-fill 得到）。
    limit_matrix: 日度×标的，当日涨跌幅（百分比），用于涨停买不到/跌停卖不出判断。
    返回净值序列（起始=1，长度 = 1 + 交易日数）。
    """
    up = get(cfg, "trading", "limit_up_pct", default=9.5) if cfg else 9.5
    down = get(cfg, "trading", "limit_down_pct", default=-9.5) if cfg else -9.5
    cols = list(ret_matrix.columns)
    dates = list(ret_matrix.index)

    weights = pd.Series(0.0, index=cols)
    nav = [1.0]
    for i, d in enumerate(dates):
        ideal = weight_panel.loc[d].reindex(cols).fillna(0.0)
        is_rebal = not ideal.equals(weights)
        if is_rebal:
            eff = ideal.copy()
            if limit_matrix is not None and d in limit_matrix.index:
                lim = limit_matrix.loc[d]
                # 涨停买不到：新持仓当日涨停 -> 该标的不计入（权重置 0）
                for c in eff.index:
                    if eff[c] > 0 and bool(is_limit_up(lim.get(c), up)):
                        eff[c] = 0.0
                # 跌停卖不出：旧持仓当日跌停且本期被换出 -> 继续持有
                for c in weights.index:
                    if weights[c] > 0 and eff[c] == 0 and bool(is_limit_down(lim.get(c), down)):
                        eff[c] = weights[c]
            # 不做归一化：权重和 < 1 即代表持有现金（熊市缩放/涨停买不到的剩余部分），
            # 现金按 0 收益计入净值，回测与实盘口径一致。
            turn = (eff - weights).abs().sum() / 2.0
            nav[-1] *= (1 - cost * turn)
            weights = eff
        day_ret = ret_matrix.loc[d].reindex(cols).fillna(0.0)
        nav.append(nav[-1] * (1 + float((weights * day_ret).sum())))
    return pd.Series(nav)


def compute_metrics(nav: pd.Series, benchmark_nav: pd.Series | None = None) -> dict:
    nav = nav.dropna()
    if len(nav) < 2:
        return {}
    rets = nav.pct_change().dropna()
    total = nav.iloc[-1] - 1
    years = len(nav) / 252.0
    ann = (1 + total) ** (1 / years) - 1 if years > 0 else 0
    sharpe = rets.mean() / rets.std() * np.sqrt(252) if rets.std() > 0 else 0
    peak = nav.cummax()
    mdd = (nav / peak - 1).min()
    out = {
        "total_return": float(total),
        "annual_return": float(ann),
        "sharpe": float(sharpe),
        "max_drawdown": float(mdd),
        "vol_annual": float(rets.std() * np.sqrt(252)),
    }
    if benchmark_nav is not None and len(benchmark_nav) == len(nav):
        bret = benchmark_nav.pct_change().dropna()
        excess = (rets - bret).mean() / (rets - bret).std() * np.sqrt(252) if (rets - bret).std() > 0 else 0
        out["excess_sharpe_vs_bench"] = float(excess)
        out["bench_total_return"] = float(benchmark_nav.iloc[-1] - 1)
    return out


# ---------------- 数据编排 ----------------

def _build_panel(fetcher: DataFetcher, codes, col: str) -> pd.DataFrame:
    """构建日度面板（col 为 '收盘' 或 '涨跌幅'）。"""
    series = {}
    for code in codes:
        try:
            if col == "收盘":
                hist = fetcher.get_stock_hist(code)
            else:
                hist = fetcher.get_stock_hist(code)
            if hist is None or hist.empty or col not in hist.columns:
                continue
            val = pd.to_numeric(hist[col], errors="coerce").dropna()
            series[code] = val
        except Exception:
            continue
    if not series:
        return pd.DataFrame()
    return pd.DataFrame(series).sort_index()


def _fetch_held_fundamentals(fetcher: DataFetcher, codes) -> pd.DataFrame:
    """质量/估值/资金流：取近期快照并持有（近似）。"""
    rows = []
    for code in codes:
        try:
            fin = fetcher.get_stock_financials(code)
            rows.append({
                "code": code,
                "roe": fin.get("roe"), "debt_ratio": fin.get("debt_ratio"),
                "pe": fin.get("pe"), "pb": fin.get("pb"),
                "dividend_yield": fin.get("dividend_yield"),
            })
        except Exception:
            rows.append({"code": code})
    return pd.DataFrame(rows)


def _cap_turnover_panel(prev: pd.Series, cur: pd.Series, max_turn: float) -> pd.Series:
    """回测版换手控制：限制 cur 中"新进入"标的数量不超过 max_turn*上期数量。"""
    prev_codes = set(prev[prev > 0].index)
    cur_codes = set(cur[cur > 0].index)
    new_codes = cur_codes - prev_codes
    if not new_codes:
        return cur
    allow = int(round(max_turn * max(len(prev_codes), 1)))
    # 按 cur 权重降序保留允许数量的新进入标的
    new_w = cur[list(new_codes)].sort_values(ascending=False)
    keep_new = set(new_w.head(allow).index)
    out = cur.copy()
    for c in new_codes - keep_new:
        out[c] = 0.0
    s = out.sum()
    return out / s if s > 0 else out


def run_backtest(fetcher: DataFetcher, cfg: dict, pool: int = 80, lookback: int = 60,
                 hold: int = 20, top_n: int = 10, rebalance: int = 21,
                 cost: float = 0.001, benchmark: str = "000300") -> dict:
    uni = fetcher.get_stock_universe()
    uni = uni.sort_values("amount", ascending=False).head(pool)
    codes = uni["code"].astype(str).tolist()
    mc_map = uni.set_index("code")["market_cap"].to_dict()

    close = _build_panel(fetcher, codes, "收盘")
    if close.shape[1] < top_n:
        raise RuntimeError(f"可用标的不够（{close.shape[1]} < {top_n}），扩大 --pool")
    pct = _build_panel(fetcher, codes, "涨跌幅")
    fund = _fetch_held_fundamentals(fetcher, codes).set_index("code")

    bench_hist = fetcher.get_index_hist(benchmark)
    bench_close = (pd.to_numeric(bench_hist["收盘"], errors="coerce").dropna()
                   if bench_hist is not None and not bench_hist.empty else None)

    # 时点化因子快照（仅调仓日）
    reb_dates = close.index[::rebalance][1:]
    score_rows = []
    for d in reb_dates:
        pos = close.index.get_loc(d)
        if pos < lookback + 1:
            continue
        win = close.iloc[: pos + 1]
        ret_5 = (win.iloc[-1] / win.iloc[-6] - 1)
        ret_20 = (win.iloc[-1] / win.iloc[-1 - 20] - 1)
        ret_60 = (win.iloc[-1] / win.iloc[-1 - 60] - 1)
        mc = pd.Series({c: mc_map.get(c) for c in codes})
        snap = pd.DataFrame({
            "ret_5": ret_5, "ret_20": ret_20, "ret_60": ret_60,
            "market_cap": mc,
            "pe": fund["pe"], "pb": fund["pb"], "dividend_yield": fund["dividend_yield"],
            "roe": fund["roe"], "debt_ratio": fund["debt_ratio"],
            "fund_flow_5": 0.0, "fund_flow_20": 0.0, "industry": None,
        }).T
        snap = snap.T
        snap = score_universe(snap, cfg, "stock")
        snap = snap.reset_index()  # code 在 index 上 -> 转成列
        snap = snap.rename(columns={snap.columns[0]: "code"})  # 统一列名为 code
        snap["date"] = d
        score_rows.append(snap[["date", "code", "score"]])

    if not score_rows:
        raise RuntimeError("未生成任何调仓期因子快照，检查历史长度。")
    score_panel = pd.concat(score_rows).pivot(index="date", columns="code", values="score")

    # 日度收益面板：保留全部交易日（从首个调仓日起），用于逐日持有模拟；
    # 权重面板随后会 forward-fill 到这些交易日，而非仅在调仓日步进。
    ret_matrix = close.pct_change().dropna()
    ret_matrix = ret_matrix[score_panel.columns]
    ret_matrix = ret_matrix.loc[score_panel.index[0]:]  # 从首个调仓日开始
    vol_panel = ret_matrix.rolling(60).std() * np.sqrt(252) * 100.0  # 年化波动率(百分比)

    # 市场状态缩放：每个调仓日按指数 vs MA(ma_window) 决定仓位缩放（与 finalize 同口径）。
    # 熊市 risk_off -> 把权重乘 risk_off_scale（如 0.3），权重和 < 1，回测据此持有现金，
    # 避免"永远满仓"虚高收益，使回测与实盘口径一致。
    regime_enabled = get(cfg, "regime", "enabled", default=True)
    regime_close = None
    if regime_enabled:
        rg_idx = get(cfg, "regime", "index", default="000300")
        rh = fetcher.get_index_hist(rg_idx)
        if rh is not None and not rh.empty and "收盘" in rh.columns:
            regime_close = pd.to_numeric(rh["收盘"], errors="coerce").dropna()

    # 每期目标权重（风险平价），应用 A2 换手控制 与 市场状态缩放
    max_turn = get(cfg, "turnover", "max_turnover_pct", default=1.0)
    w_rows = []
    for d in score_panel.index:
        sc = score_panel.loc[d].dropna().sort_values(ascending=False)
        if len(sc) < top_n:
            w_rows.append(pd.Series(0.0, index=score_panel.columns))
            continue
        sel = sc.head(top_n).index
        w = portfolio_weights(vol_panel.loc[d, sel], cfg)
        w = w.reindex(score_panel.columns).fillna(0.0)
        w_rows.append(w)
    weight_panel = pd.DataFrame(w_rows, index=score_panel.index)
    if max_turn < 1.0:
        fixed = [weight_panel.iloc[0]]
        for k in range(1, len(weight_panel)):
            fixed.append(_cap_turnover_panel(weight_panel.iloc[k - 1], weight_panel.iloc[k], max_turn))
        weight_panel = pd.DataFrame(fixed, index=score_panel.index)
    # 市场状态缩放：在 A2 换手控制之后施加，避免被归一化抹掉现金比例。
    # 熊市 risk_off -> 权重乘 risk_off_scale（如 0.3），权重和 < 1 代表持有现金。
    if regime_enabled and regime_close is not None:
        scaled = []
        for d in weight_panel.index:
            w = weight_panel.loc[d]
            if d in regime_close.index:
                w = w * regime_scale(regime_close, cfg, as_of=d)
            scaled.append(w)
        weight_panel = pd.DataFrame(scaled, index=weight_panel.index)
    # forward-fill 到全部交易日
    weight_panel = weight_panel.reindex(ret_matrix.index).ffill().fillna(0.0)

    limit_matrix = pct.reindex(ret_matrix.index) if not pct.empty else None

    nav = simulate_portfolio(ret_matrix, weight_panel, limit_matrix, cost, cfg)

    # 基准净值（相同交易日轴）
    bench_nav = None
    if bench_close is not None:
        bc = bench_close.reindex(ret_matrix.index).ffill().dropna()
        if len(bc) > 1:
            bret = bc.pct_change().fillna(0.0)
            bn = (1 + bret).cumprod()
            bench_nav = pd.concat([pd.Series([1.0]), bn]).reset_index(drop=True)
            bench_nav = bench_nav.iloc[: len(nav)].reset_index(drop=True)

    metrics = compute_metrics(nav, bench_nav)

    half = len(nav) // 2
    seg = {
        "in_sample": compute_metrics(nav.iloc[:half], bench_nav.iloc[:half] if bench_nav is not None else None),
        "out_sample": compute_metrics(nav.iloc[half:], bench_nav.iloc[half:] if bench_nav is not None else None),
    }
    return {"nav": nav, "metrics": metrics, "segments": seg, "bench_nav": bench_nav,
            "bench_total_return": (bench_nav.iloc[-1] - 1) if bench_nav is not None else None}


# ---------------- API 序列化与离线演示 ----------------

def _clean_metrics(m: dict) -> dict:
    out = {}
    for k, v in m.items():
        out[k] = round(float(v), 4) if isinstance(v, (int, float)) and v == v else v
    return out


def to_api_result(res: dict) -> dict:
    """把 run_backtest 的返回整理成 API/前端友好的 JSON（净值转成 [i,value] 列表）。"""

    def series_to_list(s):
        if s is None:
            return None
        is_date = isinstance(s.index, pd.DatetimeIndex)
        out = []
        for i, (d, v) in enumerate(s.items()):
            pt = {"i": i, "value": round(float(v), 6)}
            if is_date:
                pt["date"] = str(d) if hasattr(d, "strftime") else str(d)[:10]
            out.append(pt)
        return out

    return {
        "nav": series_to_list(res.get("nav")),
        "bench_nav": series_to_list(res.get("bench_nav")),
        "metrics": _clean_metrics(res.get("metrics", {})),
        "segments": {k: _clean_metrics(v) for k, v in res.get("segments", {}).items()},
        "bench_total_return": res.get("bench_total_return"),
    }


class _DemoFetcher:
    """合成数据 fetcher：无需 AKShare / 网络，用于离线演示与自测。"""

    def __init__(self, n_stocks: int = 12, n_days: int = 250, seed: int = 7):
        self._rng = np.random.default_rng(seed)
        self._dates = pd.date_range("2023-01-01", periods=n_days, freq="B")
        self._codes = [f"C{i:03d}" for i in range(1, n_stocks + 1)]
        self._close, self._fin = {}, {}
        for code in self._codes:
            r = self._rng.normal(0.0006, 0.02, n_days)
            px = 10 * np.cumprod(1 + r)
            self._close[code] = pd.Series(px, index=self._dates)
            self._fin[code] = {
                "roe": float(self._rng.uniform(0.05, 0.25)),
                "debt_ratio": float(self._rng.uniform(0.2, 0.7)),
                "pe": float(self._rng.uniform(8, 40)),
                "pb": float(self._rng.uniform(0.8, 5)),
                "dividend_yield": float(self._rng.uniform(0.0, 0.04)),
            }
        # 指数：先涨后跌，制造一段 risk_off，使 regime 缩放有可见效果
        idx = np.concatenate([np.linspace(3000, 3400, n_days - 60),
                              np.linspace(3400, 2900, 60)])
        self._index = pd.Series(idx, index=self._dates)

    def get_stock_universe(self):
        return pd.DataFrame({
            "code": self._codes,
            "name": [f"演示股{i}" for i in range(1, len(self._codes) + 1)],
            "market_cap": [1e10] * len(self._codes),
            "amount": [1e9] * len(self._codes),
        })

    def get_stock_hist(self, code):
        code = str(code)
        if code not in self._close:
            return pd.DataFrame()
        s = self._close[code]
        df = pd.DataFrame({"收盘": s})
        df["涨跌幅"] = s.pct_change().fillna(0.0) * 100.0
        return df

    def get_index_hist(self, sym=None):
        return pd.DataFrame({"收盘": self._index})

    def get_stock_financials(self, code):
        return self._fin.get(str(code), {})

    def close(self):
        pass


def demo_backtest(cfg: dict | None = None, **kw) -> dict:
    """用合成数据跑一次回测，返回 run_backtest 原始结果（离线演示/自测用）。"""
    if cfg is None:
        cfg = load_config()
    return run_backtest(_DemoFetcher(), cfg, **kw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true",
                    help="用合成数据离线演示回测（无需 AKShare / 网络），适合自测与展示")
    ap.add_argument("--pool", type=int, default=80)
    ap.add_argument("--lookback", type=int, default=60)
    ap.add_argument("--hold", type=int, default=20)
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--rebalance", type=int, default=21)
    ap.add_argument("--cost", type=float, default=0.001)
    ap.add_argument("--benchmark", type=str, default="000300")
    ap.add_argument("--out", type=str, default=None,
                    help="把回测结果写成 JSON（API 友好格式），便于前端消费")
    args = ap.parse_args()

    cfg = load_config()
    if args.demo:
        f = _DemoFetcher()
    else:
        f = DataFetcher(sqlite_path=get(cfg, "data", "sqlite_path", default="data/quantpick.db"))
    try:
        res = run_backtest(f, cfg, pool=args.pool, lookback=args.lookback,
                           hold=args.hold, top_n=args.top, rebalance=args.rebalance,
                           cost=args.cost, benchmark=args.benchmark)
    finally:
        f.close()

    m = res["metrics"]
    print("=== 策略指标 ===")
    for k, v in m.items():
        print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")
    print("=== 样本内 / 样本外 ===")
    for seg, sm in res["segments"].items():
        print(f"  [{seg}] total={sm.get('total_return',0):.2%} sharpe={sm.get('sharpe',0):.2f} mdd={sm.get('max_drawdown',0):.2%}")
    print(f"基准(沪深300)总收益: {res['bench_total_return']:.2%}" if res['bench_total_return'] is not None else "基准: 无")

    if args.out:
        import json as _json
        with open(args.out, "w", encoding="utf-8") as fh:
            _json.dump(to_api_result(res), fh, ensure_ascii=False, indent=2)
        print(f"\n已写出 API 结果 -> {args.out}")


if __name__ == "__main__":
    main()
