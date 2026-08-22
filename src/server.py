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


if __name__ == "__main__":
    cfg = load_config()
    host = get(cfg, "server", "host", default="0.0.0.0")
    port = get(cfg, "server", "port", default=8080)
    app.run(host=host, port=port, debug=False)
