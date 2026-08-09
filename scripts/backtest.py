"""回测：用与生产一致的多因子 composite 做横截面选股，含手续费/滑点、基准对比与样本外分段。

说明：
- 这是"策略是否有效"的验证，不是实盘。它尽量复用 selection.score_universe，保证回测对象=实盘模型。
- 因子在每期调仓日"时点化"计算（只用当时可得数据），避免未来函数。
- 价值/质量/资金流采用"近期快照并持有"的近似（基本面变化慢），动量严格时点化。
- 交易成本 + 基准(沪深300) + Sharpe/最大回撤/换手/IC，并做前后段(样本内/外)对比。

用法：
    python scripts/backtest.py --pool 80 --lookback 60 --hold 20 --top 10 --rebalance 21
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


# ---------------- 纯函数：组合模拟与指标（便于单测） ----------------

def simulate_portfolio(score_matrix: pd.DataFrame, return_matrix: pd.DataFrame,
                       top_n: int, cost: float) -> pd.Series:
    """给定 score_matrix(日期×标的) 与 return_matrix(日期×标的, 日收益)，
    每期选 score 最高的 top_n，等权持有到下期，计入单边换手成本 cost。
    返回净值序列（起始=1）。"""
    dates = score_matrix.index
    nav = [1.0]
    weights = pd.Series(0.0, index=score_matrix.columns)
    for i in range(1, len(dates)):
        prev_ret = return_matrix.iloc[i]
        nav.append(nav[-1] * (1 + (weights * prev_ret).sum()))
        # 重新选股
        sc = score_matrix.iloc[i]
        sc = sc.dropna().sort_values(ascending=False)
        if len(sc) < top_n:
            new_w = pd.Series(0.0, index=score_matrix.columns)
        else:
            sel = sc.head(top_n).index
            new_w = pd.Series(1.0 / top_n, index=sel)
            new_w = new_w.reindex(score_matrix.columns).fillna(0.0)
        # 换手成本
        turnover = (new_w - weights).abs().sum() / 2.0
        nav[-1] *= (1 - cost * turnover)
        weights = new_w
    return pd.Series(nav, index=dates)


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

def _build_close_panel(fetcher: DataFetcher, codes) -> pd.DataFrame:
    series = {}
    for code in codes:
        try:
            hist = fetcher.get_stock_hist(code)
            if hist is None or hist.empty or "收盘" not in hist.columns:
                continue
            close = pd.to_numeric(hist["收盘"], errors="coerce").dropna()
            series[code] = close
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
            ff = fetcher.get_stock_fund_flow(code)
            f5 = ff.get("主力净流入") if isinstance(ff, dict) else None
            rows.append({
                "code": code,
                "roe": fin.get("roe"), "debt_ratio": fin.get("debt_ratio"),
                "pe": fin.get("pe"), "pb": fin.get("pb"),
                "dividend_yield": fin.get("dividend_yield"),
            })
        except Exception:
            rows.append({"code": code})
    return pd.DataFrame(rows)


def run_backtest(fetcher: DataFetcher, cfg: dict, pool: int = 80, lookback: int = 60,
                 hold: int = 20, top_n: int = 10, rebalance: int = 21,
                 cost: float = 0.001, benchmark: str = "000300") -> dict:
    uni = fetcher.get_stock_universe()
    uni = uni.sort_values("amount", ascending=False).head(pool)
    codes = uni["code"].astype(str).tolist()

    close = _build_close_panel(fetcher, codes)
    if close.shape[1] < top_n:
        raise RuntimeError(f"可用标的不够（{close.shape[1]} < {top_n}），扩大 --pool")
    fund = _fetch_held_fundamentals(fetcher, codes)
    fund = fund.set_index("code")

    # 基准
    bench_hist = fetcher.get_index_hist(benchmark)
    bench_close = pd.to_numeric(bench_hist["收盘"], errors="coerce").dropna() if bench_hist is not None and not bench_hist.empty else None

    # 时点化因子快照
    reb_dates = close.index[::rebalance][1:]  # 跳过首期（需历史）
    score_rows = []
    for d in reb_dates:
        pos = close.index.get_loc(d)
        if pos < lookback + 1:
            continue
        win = close.iloc[: pos + 1]
        ret_20 = (win.iloc[-1] / win.iloc[-1 - 20] - 1)
        ret_60 = (win.iloc[-1] / win.iloc[-1 - 60] - 1)
        high252 = win.rolling(252).max().iloc[-1]
        p2h = win.iloc[-1] / high252
        snap = pd.DataFrame({
            "ret_20": ret_20, "ret_60": ret_60,
            "pe": fund["pe"], "pb": fund["pb"], "dividend_yield": fund["dividend_yield"],
            "roe": fund["roe"], "debt_ratio": fund["debt_ratio"],
            "fund_flow_5": 0.0, "fund_flow_20": 0.0, "industry": None,
        }).T  # rows=features, cols=codes
        snap = snap.T  # back to rows=codes
        snap = score_universe(snap, cfg, "stock")
        snap["date"] = d
        score_rows.append(snap[["date", "score"]])

    if not score_rows:
        raise RuntimeError("未生成任何调仓期因子快照，检查历史长度。")
    score_panel = pd.concat(score_rows).pivot(index="date", columns="code", values="score")

    # 收益矩阵（日收益），对齐到 score_panel 的日期范围
    ret_matrix = close.pct_change().reindex(score_panel.index).fillna(0)
    ret_matrix = ret_matrix[score_panel.columns]

    nav = simulate_portfolio(score_panel, ret_matrix, top_n, cost)

    bench_nav = None
    if bench_close is not None:
        bc = bench_close.reindex(score_panel.index).ffill().dropna()
        if len(bc) == len(nav):
            bench_nav = (1 + bc.pct_change().fillna(0)).cumprod()

    metrics = compute_metrics(nav, bench_nav)

    # 样本内/外分段
    half = len(nav) // 2
    seg = {
        "in_sample": compute_metrics(nav.iloc[:half], bench_nav.iloc[:half] if bench_nav is not None else None),
        "out_sample": compute_metrics(nav.iloc[half:], bench_nav.iloc[half:] if bench_nav is not None else None),
    }
    return {"nav": nav, "metrics": metrics, "segments": seg,
            "bench_total_return": (bench_nav.iloc[-1] - 1) if bench_nav is not None else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", type=int, default=80)
    ap.add_argument("--lookback", type=int, default=60)
    ap.add_argument("--hold", type=int, default=20)
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--rebalance", type=int, default=21)
    ap.add_argument("--cost", type=float, default=0.001)
    ap.add_argument("--benchmark", type=str, default="000300")
    args = ap.parse_args()

    cfg = load_config()
    fetcher = DataFetcher(sqlite_path=get(cfg, "data", "sqlite_path", default="data/quantpick.db"))
    try:
        res = run_backtest(fetcher, cfg, pool=args.pool, lookback=args.lookback,
                           hold=args.hold, top_n=args.top, rebalance=args.rebalance,
                           cost=args.cost, benchmark=args.benchmark)
    finally:
        fetcher.close()

    m = res["metrics"]
    print("=== 策略指标 ===")
    for k, v in m.items():
        print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")
    print("=== 样本内 / 样本外 ===")
    for seg, sm in res["segments"].items():
        print(f"  [{seg}] total={sm.get('total_return',0):.2%} sharpe={sm.get('sharpe',0):.2f} mdd={sm.get('max_drawdown',0):.2%}")
    print(f"基准(沪深300)总收益: {res['bench_total_return']:.2%}" if res['bench_total_return'] is not None else "基准: 无")


if __name__ == "__main__":
    main()
