"""每日扫描入口：收盘后运行，生成股+ETF 候选清单、应用风控、推送、落盘 JSON 与历史。

用法：
    python scripts/daily_scan.py                 # 收盘后跑，推送+存盘+留存历史
    python scripts/daily_scan.py --top 5         # 只取前 5
    python scripts/daily_scan.py --no-notify     # 不推送（仅打印+存盘）
    python scripts/daily_scan.py --out result.json

建议挂 crontab（交易日 15:30）：
    30 15 * * 1-5 cd /path/QuantPick && /path/.venv/bin/python scripts/daily_scan.py
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import load_config, get
from src.selection import run_selection
from src.risk import finalize
from src.notify import build_report, notify, alert
from src.data import DataFetcher, is_trading_day
from src import history as history_mod

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("quantpick.scan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=None)
    ap.add_argument("--no-notify", action="store_true")
    ap.add_argument("--out", type=str, default="data/candidates.json")
    args = ap.parse_args()

    if not is_trading_day():
        print("[skip] 非交易日，跳过扫描")
        return

    cfg = load_config()
    if args.top:
        sel = cfg.setdefault("selection", {})
        sel["stock"] = {**sel.get("stock", {}), "top_n": args.top}
        sel["etf"] = {**sel.get("etf", {}), "top_n": args.top}

    db = get(cfg, "data", "sqlite_path", default="data/quantpick.db")
    fetcher = DataFetcher(sqlite_path=db,
                          cache_days=get(cfg, "data", "cache_days", default=1))
    try:
        res = run_selection(cfg, fetcher)
        res = finalize(res, cfg, fetcher)
    finally:
        fetcher.close()

    stocks = res.get("stocks")
    etfs = res.get("etfs")
    regime = res.get("regime", {"state": "risk_on", "scale": 1.0})

    # 空结果告警：数据没取到或市场过滤后为空，绝不静默当成正常
    if (stocks is None or stocks.empty) and (etfs is None or etfs.empty):
        alert(cfg, "本期候选为空（数据未取到或市场状态过滤），请检查数据源与网络。")
        logger.error("候选为空，已发告警并中止本次推送/存盘。")
        return

    report = build_report(stocks, etfs, regime)
    print(report)

    # 落盘
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    payload = {
        "regime": regime,
        "stocks": (stocks.to_dict(orient="records")
                   if stocks is not None and not stocks.empty else []),
        "etfs": (etfs.to_dict(orient="records")
                 if etfs is not None and not etfs.empty else []),
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    print(f"[ok] 已保存 {args.out}")

    # 留存历史（用于复盘 / 战绩）
    run_date = date.today().isoformat()
    if stocks is not None and not stocks.empty:
        history_mod.save_run(db, run_date, "stock", stocks)
    if etfs is not None and not etfs.empty:
        history_mod.save_run(db, run_date, "etf", etfs)
    print(f"[ok] 已留存历史 {run_date}")

    if not args.no_notify:
        notify(cfg, report)


if __name__ == "__main__":
    main()
