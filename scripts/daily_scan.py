"""每日扫描入口：收盘后运行，生成股+ETF 候选清单、应用风控、推送、落盘 JSON。

用法：
    python scripts/daily_scan.py                 # 收盘后跑，推送+存盘
    python scripts/daily_scan.py --top 5         # 只取前 5
    python scripts/daily_scan.py --no-notify     # 不推送（仅打印+存盘）
    python scripts/daily_scan.py --out result.json

建议挂 crontab（交易日 15:30）：
    30 15 * * 1-5 cd /path/QuantPick && /path/.venv/bin/python scripts/daily_scan.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import load_config, get
from src.selection import run_selection
from src.risk import apply_risk, deduplicate_by_correlation
from src.notify import build_report, notify
from src.data import DataFetcher, is_trading_day


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
        cfg.setdefault("selection", {})["stock"] = {**cfg.get("selection", {}).get("stock", {}), "top_n": args.top}
        cfg["selection"]["etf"] = {**cfg.get("selection", {}).get("etf", {}), "top_n": args.top}

    res = run_selection(cfg)
    res = apply_risk(res.get("stocks"), res.get("etfs"), cfg)

    # 相关性去重：保留高分且低相关的股票子集
    if "stocks" in res and not res["stocks"].empty:
        fetcher2 = DataFetcher(
            sqlite_path=get(cfg, "data", "sqlite_path", default="data/quantpick.db"),
            cache_days=get(cfg, "data", "cache_days", default=1),
        )
        try:
            cands = list(zip(res["stocks"]["code"], res["stocks"]["score"]))
            deduped = deduplicate_by_correlation(
                fetcher2, cands, get(cfg, "risk", "max_correlation", default=0.7))
            keep = {c for c, _ in deduped}
            res["stocks"] = res["stocks"][res["stocks"]["code"].isin(keep)]
        finally:
            fetcher2.close()

    stocks = res.get("stocks")
    etfs = res.get("etfs")
    report = build_report(stocks, etfs)
    print(report)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    payload = {
        "stocks": (stocks.to_dict(orient="records")
                   if stocks is not None and not stocks.empty else []),
        "etfs": (etfs.to_dict(orient="records")
                 if etfs is not None and not etfs.empty else []),
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    print(f"[ok] 已保存 {args.out}")

    if not args.no_notify:
        notify(cfg, report)


if __name__ == "__main__":
    main()
