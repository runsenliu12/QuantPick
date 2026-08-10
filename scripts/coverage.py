"""因子数据覆盖率诊断（CLI）。

实跑一遍生产取数，统计各因子在候选池上的取到率，标出"在空转"的关键因子。
需要联网 + akshare（在部署机/本机运行；沙箱无外网时仅逻辑可单测）。

用法：
    python scripts/coverage.py                  # 打印文本报告
    python scripts/coverage.py --json cov.json  # 同时存 JSON
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import load_config
from src.data import DataFetcher
from src import coverage as cov


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=str, default=None, help="另存 JSON 路径")
    args = ap.parse_args()

    cfg = load_config()
    db = cfg.get("data", {}).get("sqlite_path", "data/quantpick.db")
    fetcher = DataFetcher(sqlite_path=db,
                          cache_days=cfg.get("data", {}).get("cache_days", 1))
    try:
        rep = cov.factor_coverage(fetcher, cfg)
    finally:
        fetcher.close()

    print(cov.format_report(rep))

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=2)
        print(f"\n[ok] JSON 已保存 {args.json}")


if __name__ == "__main__":
    main()
