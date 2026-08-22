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

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import load_config, get
from src.selection import run_selection
from src.risk import finalize
from src.notify import build_report, notify, alert
from src.data import DataFetcher, is_trading_day
from src import history as history_mod
from src import us_etf as us_mod

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("quantpick.scan")


def apply_turnover(new_df, prev_df, cfg, top_n):
    """A2 换手率控制 + 再平衡粘性：限制每期被替换的标的数量，降低摩擦成本。

    规则：
    - prev 中仍在候选且分数未明显下滑(>= prev_score - min_score_gap)的标的保留。
    - 其余名额用 prev 之外的新候选按 rank 补足，但补入数量不超过
      max_turnover_pct * 上期数量。
    仓位沿用本期 risk 计算的 position_pct（与 regime 缩放一致）。
    """
    if prev_df is None or prev_df.empty or new_df is None or new_df.empty:
        return new_df
    if not get(cfg, "turnover", "enabled", default=True):
        return new_df

    max_turn = get(cfg, "turnover", "max_turnover_pct", default=1.0)
    min_gap = get(cfg, "turnover", "min_score_gap", default=0.0)

    prev = prev_df.set_index("code")
    prev_codes = set(prev.index)
    new_idx = new_df.set_index("code")

    keep_codes = [
        c for c in prev_codes
        if c in new_idx.index
        and float(new_idx.loc[c, "score"]) >= float(prev.loc[c, "score"]) - min_gap
    ]
    kept = new_df[new_df["code"].astype(str).isin(keep_codes)].copy()
    fresh = new_df[~new_df["code"].astype(str).isin(prev_codes)].copy()

    allow = int(round(max_turn * max(len(prev_codes), 1)))
    room = max(0, top_n - len(keep_codes))
    allow = min(allow, room)
    fresh = fresh.sort_values("rank").head(allow)

    out = pd.concat([kept, fresh], ignore_index=True)
    out = out.sort_values("rank").reset_index(drop=True)
    out["rank"] = out.index + 1
    return out


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

        # A2 换手率控制 + 再平衡粘性：对比上一期，限制每期被替换的标的数量
        if get(cfg, "turnover", "enabled", default=True):
            top_s = get(cfg, "selection", "stock", "top_n", default=10)
            top_e = get(cfg, "selection", "etf", "top_n", default=10)
            prev_s = history_mod.load_latest_run(db, "stock")
            prev_e = history_mod.load_latest_run(db, "etf")
            if "stocks" in res and not res["stocks"].empty:
                res["stocks"] = apply_turnover(res["stocks"], prev_s, cfg, top_s)
            if "etfs" in res and not res["etfs"].empty:
                res["etfs"] = apply_turnover(res["etfs"], prev_e, cfg, top_e)
    finally:
        fetcher.close()

    stocks = res.get("stocks")
    etfs = res.get("etfs")
    regime = res.get("regime", {"state": "risk_on", "scale": 1.0})

    # 美股 ETF 选基（默认关闭，需在 config 启用；失败不影响 A 股流程）
    us = None
    if get(cfg, "us_etf", "enabled", default=False):
        try:
            us = us_mod.rank_us_etfs(cfg)
            if us is not None and not us.empty:
                print(us_mod.build_us_report(us))
        except Exception as e:
            logger.warning("美股 ETF 选基失败（已跳过，不影响 A 股）: %s", e)
            us = None

    # 空结果告警：数据没取到或市场过滤后为空，绝不静默当成正常
    if (stocks is None or stocks.empty) and (etfs is None or etfs.empty):
        alert(cfg, "本期候选为空（数据未取到或市场状态过滤），请检查数据源与网络。")
        logger.error("候选为空，已发告警并中止本次推送/存盘。")
        return

    report = build_report(stocks, etfs, regime)
    if us is not None and not us.empty:
        report += us_mod.build_us_report(us)
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
    if us is not None and not us.empty:
        history_mod.save_run(db, run_date, "us_etf", us)
    print(f"[ok] 已留存历史 {run_date}")

    if not args.no_notify:
        notify(cfg, report)


if __name__ == "__main__":
    main()
