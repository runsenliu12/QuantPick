"""纸上交易对账入口：把历史推荐与实际行情对账，输出真实战绩报告。

用法：
    python scripts/paper_trading.py                  # 计算并保存报告到 data/
    python scripts/paper_trading.py --horizons 5 20  # 只看 5/20 日
    python scripts/paper_trading.py --out-dir out    # 指定输出目录
    python scripts/paper_trading.py --no-save        # 仅打印摘要

依赖：data/quantpick.db 中需有 daily_scan 写入的 selections（推荐记录）。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import load_config, get
from src.performance import compute_performance, build_html_report, save_report
from src.notify import notify, alert

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("quantpick.paper")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizons", type=int, nargs="+", default=None,
                    help="持有期（交易日），默认 5 20 60")
    ap.add_argument("--out-dir", type=str, default="data")
    ap.add_argument("--out-name", type=str, default="performance")
    ap.add_argument("--no-save", action="store_true")
    ap.add_argument("--notify", action="store_true", help="把战绩摘要推送到飞书/企微")
    args = ap.parse_args()

    cfg = load_config()
    db = get(cfg, "data", "sqlite_path", default="data/quantpick.db")
    horizons = args.horizons or get(cfg, "performance", "horizons", default=[5, 20, 60])

    res = compute_performance(db, cfg, horizons=tuple(horizons))
    if res.get("empty"):
        print("[paper]", res.get("message"))
        return

    # 摘要
    p = res["portfolio"]; b = res["benchmark_metrics"]
    print(f"=== QuantPick 纸上交易战绩（基准 {res['benchmark_name']}）===")
    print(f"样本: {res['rec_count']} 条推荐 / {res['basket_count']} 个推荐日篮子")
    print(f"策略总收益 {p['total_return']}% | 基准 {b['total_return']}% | 超额 {res['excess_return']}%")
    print(f"策略 Sharpe {p['sharpe']} | 年化 {p['annualized']}% | 最大回撤 {p['max_drawdown']}%")
    print("分持有期命中率:")
    for h, m in res["per_horizon"].items():
        print(f"  {h}日: 样本{m['count']} 命中率{m['win_rate']}% 平均{m['mean_return']}% 中位{m['median_return']}%")

    if not args.no_save:
        out_json = os.path.join(args.out_dir, f"{args.out_name}.json")
        out_html = os.path.join(args.out_dir, f"{args.out_name}.html")
        save_report(res, out_json, out_html)
        print(f"[ok] 已保存 {out_json} 与 {out_html}")

    if args.notify:
        try:
            lines = [f"📊 QuantPick 战绩（基准 {res['benchmark_name']}）",
                     f"样本 {res['rec_count']} 条 | 策略 {p['total_return']}% / 基准 {b['total_return']}% / 超额 {res['excess_return']}%",
                     f"Sharpe {p['sharpe']} | 回撤 {p['max_drawdown']}%"]
            for h, m in res["per_horizon"].items():
                lines.append(f"{h}日: 命中 {m['win_rate']}% 均值 {m['mean_return']}%")
            notify(cfg, "\n".join(lines))
        except Exception as e:
            logger.warning("战绩推送失败: %s", e)


if __name__ == "__main__":
    main()
