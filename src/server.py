"""Web 看板：Flask 提供候选清单 API 与简单页面，适合挂服务器常驻访问。

运行：python -m src.server   （项目根目录下执行）
访问：http://服务器IP:8080
"""
from __future__ import annotations

import os
import time
from flask import Flask, jsonify, render_template, request
from flask_cors import CORS

from src.config import load_config, get
from src.selection import run_selection
from src.risk import finalize
from src.data import DataFetcher
from src import history as history_mod

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = Flask(__name__, template_folder=os.path.join(_ROOT, "web", "templates"))
CORS(app)

_cache = {"ts": 0.0, "data": None}
_TTL = 300  # 秒


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
    return render_template("index.html")


@app.route("/api/candidates")
def api_candidates():
    return jsonify(get_candidates(force=request.args.get("force") == "1"))


@app.route("/api/history")
def api_history():
    cfg = load_config()
    db = get(cfg, "data", "sqlite_path", default="data/quantpick.db")
    return jsonify(history_mod.load_history(db, limit=200))


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    cfg = load_config()
    host = get(cfg, "server", "host", default="0.0.0.0")
    port = get(cfg, "server", "port", default=8080)
    app.run(host=host, port=port, debug=False)
