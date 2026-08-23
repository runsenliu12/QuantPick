"""Web 看板：Flask 提供候选清单 API 与策略面板，适合挂服务器常驻访问。

运行：python -m src.server   （项目根目录下执行）
访问：http://服务器IP:8080
"""
from __future__ import annotations

import os
import time
import logging
from flask import Flask, jsonify, render_template, request
from flask_cors import CORS

from src.config import load_config, get
from src.selection import run_selection
from src.risk import finalize
from src.data import DataFetcher
from src import history as history_mod
from src.strategy import build_strategy
from src.performance import compute_performance

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = Flask(__name__, template_folder=os.path.join(_ROOT, "web", "templates"))
CORS(app)
logger = logging.getLogger("quantpick.server")

_cache = {"ts": 0.0, "data": None}
_TTL = 300  # 秒

_perf_cache = {"ts": 0.0, "data": None}
_PERF_TTL = 3600  # 对账较重，缓存 1 小时


def get_candidates(force: bool = False) -> dict:
    now = time.time()
    if not force and _cache["data"] and now - _cache["ts"] < _TTL:
        return _cache["data"]

    cfg = load_config()
    db = get(cfg, "data", "sqlite_path", default="data/quantpick.db")
    fetcher = DataFetcher(sqlite_path=db,
                          cache_days=get(cfg, "data", "cache_days", default=1))
    try:
        res = run_selection(cfg, fetcher)
        res = finalize(res, cfg, fetcher)
    finally:
        fetcher.close()

    out = {
        "stocks": (res["stocks"].to_dict(orient="records")
                   if "stocks" in res and not res["stocks"].empty else []),
        "etfs": (res["etfs"].to_dict(orient="records")
                 if "etfs" in res and not res["etfs"].empty else []),
        "regime": res.get("regime", {"state": "risk_on", "scale": 1.0}),
    }
    _cache.update({"ts": now, "data": out})
    return out


@app.route("/")
def index():
    cfg = load_config()
    strategy = build_strategy(cfg)
    return render_template("index.html", strategy=strategy)


@app.route("/api/strategy")
def api_strategy():
    return jsonify(build_strategy(load_config()))


# ---- 常见量化方法库元数据：仅用于 /methods 页面静态展示，不运行任何策略 ----
METHODS_META = [
    {"id": "dual_ma", "name": "双均线交叉", "category": "趋势跟踪",
     "file": "src/methods/trend.py", "params": "fast=5, slow=20",
     "risk": "震荡市假信号多，需配合止损",
     "desc": "快线上穿慢线看多、下穿看空。最经典的趋势跟踪信号。",
     "snippet": "def dual_ma_signal(close, fast=5, slow=20):\n    f, s = sma(close, fast), sma(close, slow)\n    return np.sign(f - s).ffill().fillna(0)"},
    {"id": "macd", "name": "MACD", "category": "趋势跟踪",
     "file": "src/methods/trend.py", "params": "fast=12, slow=26, signal=9",
     "risk": "滞后，趋势末尾易反复",
     "desc": "DIF 与 DEA 的金叉/死叉判断多空。",
     "snippet": "dif = ema(close, 12) - ema(close, 26)\ndea = ema(dif, 9)\nsignal = np.sign(dif - dea).ffill()"},
    {"id": "breakout", "name": "N 日突破", "category": "趋势跟踪",
     "file": "src/methods/trend.py", "params": "window=20",
     "risk": "假突破，需 ATR 止损",
     "desc": "收盘价创 N 日新高买入（海龟法则核心）。",
     "snippet": "hh = close.rolling(20).max().shift(1)\nsignal = (close > hh).astype(int)"},
    {"id": "ts_mom", "name": "时间序列动量", "category": "动量",
     "file": "src/methods/momentum.py", "params": "window=60",
     "risk": "动量崩溃（反转）",
     "desc": "过去 N 日收益为正看多、负看空。",
     "snippet": "mom = close / close.shift(60) - 1\nsignal = np.sign(mom)"},
    {"id": "xs_mom", "name": "横截面动量", "category": "动量",
     "file": "src/methods/momentum.py", "params": "window=60",
     "risk": "需足够多资产分散",
     "desc": "每个时点按收益排序，前 1/3 多、后 1/3 空。",
     "snippet": "rank = returns.rolling(60).sum().rank(pct=True)\nsignal = np.where(rank >= 2/3, 1, np.where(rank <= 1/3, -1, 0))"},
    {"id": "zscore_rev", "name": "z-score 均值回归", "category": "均值回归",
     "file": "src/methods/mean_reversion.py", "params": "window=20, entry=2.0, exit=0.5",
     "risk": "趋势市接飞刀",
     "desc": "偏离均值超过 ±entry 反向开仓，回到 ±exit 平仓。",
     "snippet": "z = zscore(close, 20)\n# |z| > entry 反向开仓, |z| < exit 平仓"},
    {"id": "boll", "name": "布林带", "category": "均值回归",
     "file": "src/methods/mean_reversion.py", "params": "window=20, k=2.0",
     "risk": "单边行情反复止损",
     "desc": "触及下轨做多、上轨做空，回中轨平仓。",
     "snippet": "mid = sma(close, 20); sd = rolling_std(close, 20)\nup = mid + 2*sd; lo = mid - 2*sd"},
    {"id": "rsi", "name": "RSI 超买超卖", "category": "均值回归",
     "file": "src/methods/mean_reversion.py", "params": "window=14, OB=70, OS=30",
     "risk": "强趋势中超买持续",
     "desc": "RSI 超卖做多、超买卖出。",
     "snippet": "rsi = 100 - 100 / (1 + rs)\nsignal = (rsi < 30) * 1 - (rsi > 70) * 1"},
    {"id": "atr", "name": "ATR 波动率", "category": "波动率",
     "file": "src/methods/volatility.py", "params": "window=14",
     "risk": "不直接给方向",
     "desc": "真实波幅均值，用于移动止损距离。",
     "snippet": "atr = max(high-low, |high-pc|, |low-pc|).rolling(14).mean()"},
    {"id": "vol_target", "name": "波动率目标", "category": "波动率",
     "file": "src/methods/volatility.py", "params": "target=0.15, window=60",
     "risk": "低波动时可能满仓",
     "desc": "波动越高仓位越低，使组合波动平稳。",
     "snippet": "w = 0.15 / (rolling_std(returns, 60) * sqrt(252))"},
    {"id": "pairs", "name": "配对交易", "category": "统计套利",
     "file": "src/methods/stat_arb.py", "params": "window=60, entry=2.0",
     "risk": "需协整，否则失效",
     "desc": "两资产价差 z-score 极端时反向开仓。",
     "snippet": "spread = log(A) - log(B)\nz = (spread - sma(spread, 60)) / std(spread, 60)"},
    {"id": "grid", "name": "网格价位", "category": "统计套利",
     "file": "src/methods/stat_arb.py", "params": "n=10, step=0.02",
     "risk": "单边下跌越跌越买",
     "desc": "生成中心上下各 n 档网格价位。",
     "snippet": "levels = [p * (1 + (i - n) * step) for i in range(2*n + 1)]"},
    {"id": "kelly", "name": "凯利公式", "category": "仓位管理",
     "file": "src/methods/position.py", "params": "frac=1.0（建议半凯利）",
     "risk": "满凯利波动极大",
     "desc": "按胜率与盈亏比确定最优下注比例。",
     "snippet": "f = (p*b - (1-p)) / b\nf = max(0.0, min(1.0, f)) * frac"},
    {"id": "risk_parity", "name": "风险平价", "category": "仓位管理",
     "file": "src/methods/position.py", "params": "迭代收敛",
     "risk": "依赖协方差估计",
     "desc": "使各资产边际风险贡献相等的权重。",
     "snippet": "# 迭代重分配，直到各资产风险贡献相等\nw = w * (1 / mrc); w /= w.sum()"},
    {"id": "multi_factor", "name": "多因子合成", "category": "多因子",
     "file": "src/methods/multi_factor.py", "params": "weights=等权",
     "risk": "因子失效则合成失效",
     "desc": "因子横截面 z-score 后加权排序选股。",
     "snippet": "z = zscore_panel(scores)\ncombined = (z * w).sum(1).sort_values(ascending=False)"},
]


@app.route("/api/methods")
def api_methods():
    return jsonify(METHODS_META)


@app.route("/methods")
def page_methods():
    return render_template("methods.html", methods=METHODS_META)


# ---- 独立专题页路由（复用 /api/* 数据，不新增后端逻辑）----
@app.route("/backtest")
def page_backtest():
    return render_template("backtest.html")


@app.route("/factors")
def page_factors():
    return render_template("factors.html", strategy=build_strategy(load_config()))


@app.route("/us-etf")
def page_us_etf():
    return render_template("us_etf.html")


@app.route("/methodology")
def page_methodology():
    return render_template("methodology.html", strategy=build_strategy(load_config()))


@app.route("/api/candidates")
def api_candidates():
    return jsonify(get_candidates(force=request.args.get("force") == "1"))


@app.route("/api/history")
def api_history():
    cfg = load_config()
    db = get(cfg, "data", "sqlite_path", default="data/quantpick.db")
    return jsonify(history_mod.load_history(db, limit=200))


def get_performance(force: bool = False) -> dict:
    now = time.time()
    if not force and _perf_cache["data"] and now - _perf_cache["ts"] < _PERF_TTL:
        return _perf_cache["data"]
    cfg = load_config()
    db = get(cfg, "data", "sqlite_path", default="data/quantpick.db")
    res = compute_performance(db, cfg)
    _perf_cache.update({"ts": now, "data": res})
    return res


@app.route("/api/performance")
def api_performance():
    return jsonify(get_performance(force=request.args.get("force") == "1"))


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


_backtest_cache = {"ts": 0.0, "_key": None, "data": None}
_BACKTEST_TTL = 3600  # 回测较重，缓存 1 小时


def get_backtest(force: bool = False, demo: bool = False) -> dict:
    now = time.time()
    key = "demo" if demo else "real"
    if not force and _backtest_cache["_key"] == key and _backtest_cache["data"] \
            and now - _backtest_cache["ts"] < _BACKTEST_TTL:
        return _backtest_cache["data"]
    # 懒导入，避免在未装 scripts 依赖时拖垮整个服务启动
    from scripts.backtest import run_backtest, to_api_result, _DemoFetcher

    cfg = load_config()
    if demo:
        fetcher = _DemoFetcher()
    else:
        db = get(cfg, "data", "sqlite_path", default="data/quantpick.db")
        fetcher = DataFetcher(sqlite_path=db,
                              cache_days=get(cfg, "data", "cache_days", default=1))
    try:
        res = run_backtest(fetcher, cfg)
    except Exception as e:  # 真实数据缺失/接口异常时优雅降级
        return {"empty": True, "message": f"回测暂不可用：{e}（可尝试 /api/backtest?demo=1 看演示）"}
    finally:
        fetcher.close()
    out = to_api_result(res)
    _backtest_cache.update({"ts": now, "_key": key, "data": out})
    return out


@app.route("/api/backtest")
def api_backtest():
    demo = request.args.get("demo") == "1"
    return jsonify(get_backtest(force=request.args.get("force") == "1", demo=demo))


_ic_cache = {"ts": 0.0, "data": None}
_IC_TTL = 3600


def get_ic() -> dict:
    now = time.time()
    if _ic_cache["data"] and now - _ic_cache["ts"] < _IC_TTL:
        return _ic_cache["data"]
    # 懒导入；当前因子历史未落库，使用带已知关系的合成数据演示 IC/ICIR。
    from src.ic import demo_ic, report
    panels, fwd = demo_ic()
    out = report(panels, fwd)
    _ic_cache.update({"ts": now, "data": out})
    return out


@app.route("/api/ic")
def api_ic():
    return jsonify(get_ic())


def get_us_etf(demo: bool = False) -> dict:
    cfg = load_config()
    if get(cfg, "us_etf", "enabled", default=False) and not demo:
        df = _us_etf_rank(cfg, demo=False)
        if df is not None and not df.empty:
            return {"source": "real", "rows": df.to_dict(orient="records")}
    df = _us_etf_rank(cfg, demo=True)
    return {"source": "demo", "rows": (df.to_dict(orient="records") if df is not None else [])}


def _us_etf_rank(cfg: dict, demo: bool):
    from src import us_etf as ue
    try:
        return ue.rank_us_etfs(cfg, demo=demo)
    except Exception as e:
        logger.warning("美股 ETF 计算失败: %s", e)
        return None


@app.route("/api/us_etf")
def api_us_etf():
    demo = request.args.get("demo") == "1"
    return jsonify(get_us_etf(demo=demo))


_quote_cache = {"ts": 0.0, "_key": None, "data": None}
_QUOTE_TTL = 3600  # 行情较重，缓存 1 小时


def get_quote(code: str, kind: str = "stock", n: int = 120, demo: bool = False) -> dict:
    """单标的行情（OHLCV）。kind=stock|etf。优先取真实历史，失败回退合成演示。"""
    now = time.time()
    key = f"{kind}:{code}:{n}"
    if not demo and _quote_cache["_key"] == key and _quote_cache["data"] \
            and now - _quote_cache["ts"] < _QUOTE_TTL:
        return _quote_cache["data"]

    rows = None
    source = "real"
    if not demo:
        cfg = load_config()
        db = get(cfg, "data", "sqlite_path", default="data/quantpick.db")
        fetcher = DataFetcher(sqlite_path=db,
                              cache_days=get(cfg, "data", "cache_days", default=1))
        try:
            if kind == "etf":
                hist = fetcher.get_etf_hist(code)
            else:
                hist = fetcher.get_stock_hist(code)
            if hist is not None and not hist.empty:
                rows = _hist_to_rows(hist, n=n)
        except Exception as e:
            logger.warning("行情获取失败 %s/%s: %s", kind, code, e)
        finally:
            fetcher.close()

    if not rows:  # 真实数据缺失 -> 合成演示 K 线
        rows = _demo_quote(kind, code, n)
        source = "demo"

    out = {"code": code, "kind": kind, "source": source, "rows": rows}
    if not demo:
        _quote_cache.update({"ts": now, "_key": key, "data": out})
    return out


def _hist_to_rows(hist: "pd.DataFrame", n: int = 120) -> list:
    """把 AKShare 行情 DataFrame 转成 OHLCV 列表（保留最近 n 条）。"""
    import pandas as pd
    df = hist.copy()
    # 统一列名：AKShare 历史列带中文（开盘/收盘/最高/最低/成交量/日期）
    colmap = {}
    for c in df.columns:
        if c in ("开盘", "open", "Open"):
            colmap[c] = "open"
        elif c in ("收盘", "close", "Close"):
            colmap[c] = "close"
        elif c in ("最高", "high", "High"):
            colmap[c] = "high"
        elif c in ("最低", "low", "Low"):
            colmap[c] = "low"
        elif c in ("成交量", "volume", "Volume"):
            colmap[c] = "volume"
        elif c in ("日期", "date", "Date"):
            colmap[c] = "date"
    if {"open", "close", "high", "low"} & set(colmap.values()):
        df = df.rename(columns=colmap)
    else:
        return []
    need = ["open", "high", "low", "close"]
    if not all(c in df.columns for c in need):
        return []
    df = df.tail(n).copy()
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    else:
        df["date"] = [str(i) for i in range(len(df))]
    out = []
    for _, r in df.iterrows():
        try:
            out.append({
                "date": str(r.get("date")),
                "open": round(float(r["open"]), 3),
                "high": round(float(r["high"]), 3),
                "low": round(float(r["low"]), 3),
                "close": round(float(r["close"]), 3),
                "volume": float(r.get("volume") or 0),
            })
        except (TypeError, ValueError):
            continue
    return out


def _demo_quote(kind: str, code: str, n: int = 120) -> list:
    """合成演示 K 线：带趋势 + 波动 + 涨跌停感，用于前端展示（非真实数据）。"""
    import numpy as np
    rng = np.random.default_rng(abs(hash(code)) % (2 ** 31))
    base = 10.0 if kind == "stock" else 1.0
    drift = rng.normal(0.0004, 0.0012)  # 区间累计趋势
    closes = [base]
    for _ in range(n - 1):
        ret = drift + rng.normal(0, 0.018)
        # 涨跌停感：单日波动封顶 ~9.8%
        ret = max(-0.098, min(0.098, ret))
        closes.append(closes[-1] * (1 + ret))
    rows = []
    prev = closes[0]
    for i, c in enumerate(closes):
        o = prev * (1 + rng.normal(0, 0.004))
        hi = max(o, c) * (1 + abs(rng.normal(0, 0.006)))
        lo = min(o, c) * (1 - abs(rng.normal(0, 0.006)))
        vol = float(rng.uniform(0.5e8, 3e8)) if kind == "stock" else float(rng.uniform(1e7, 5e7))
        rows.append({
            "date": f"D-{n - i}",
            "open": round(o, 3),
            "high": round(hi, 3),
            "low": round(lo, 3),
            "close": round(c, 3),
            "volume": round(vol, 2),
        })
        prev = c
    return rows


@app.route("/api/quote")
def api_quote():
    code = request.args.get("code", "")
    kind = request.args.get("kind", "stock")
    n = request.args.get("n", 120, type=int)
    demo = request.args.get("demo") == "1"
    if not code:
        return jsonify({"error": "code 必填"}), 400
    return jsonify(get_quote(code, kind=kind, n=n, demo=demo))


if __name__ == "__main__":
    cfg = load_config()
    host = get(cfg, "server", "host", default="0.0.0.0")
    port = get(cfg, "server", "port", default=8080)
    app.run(host=host, port=port, debug=False)
