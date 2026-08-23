"""执行层 CLI：目标组合生成 / 三平台策略代码生成 / 纸面回放。

用法（项目根目录下）：
    python -m scripts.execute target --demo            # 生成 target_portfolio.json（演示数据）
    python -m scripts.execute target                   # 生成（真实选股，需联网/缓存）
    python -m scripts.execute gen --platform ptrade     # 生成 PTrade 策略文件
    python -m scripts.execute gen --platform qmt --out strategy_qmt.py
    python -m scripts.execute gen --platform joinquant
    python -m scripts.execute paper --demo             # 纸面回放演示（合成行情）

注意：所有命令默认只"生成代码/模拟"，绝不连接券商、绝不自动下单。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import load_config
from src.execution import build_target, save_target, load_target, simulate, fetch_prices_demo
from src.execution import ptrade_adapter, qmt_adapter, joinquant_adapter

_ADAPTERS = {"ptrade": ptrade_adapter, "qmt": qmt_adapter, "joinquant": joinquant_adapter}


def _demo_candidates() -> dict:
    """离线演示候选：固定一组候选（不依赖网络/缓存），仅用于展示执行层管线。"""
    return {
        "stocks": [
            {"code": "600000.SH", "name": "浦发银行", "position_pct": 0.12, "stop_loss_pct": 0.10, "rank": 1, "score": 1.3},
            {"code": "000001.SZ", "name": "平安银行", "position_pct": 0.10, "stop_loss_pct": 0.10, "rank": 2, "score": 1.1},
            {"code": "600519.SH", "name": "贵州茅台", "position_pct": 0.08, "stop_loss_pct": 0.12, "rank": 3, "score": 1.0},
        ],
        "etfs": [
            {"code": "510300.SH", "name": "沪深300ETF", "position_pct": 0.20, "stop_loss_pct": 0.08, "rank": 1, "score": 1.5},
            {"code": "510500.SH", "name": "中证500ETF", "position_pct": 0.15, "stop_loss_pct": 0.08, "rank": 2, "score": 1.2},
        ],
        "regime": {"state": "risk_on", "scale": 1.0},
    }


def _real_candidates() -> dict:
    from src.server import get_candidates
    return get_candidates(force=True)


def main():
    p = argparse.ArgumentParser(description="QuantPick 执行层 CLI")
    sub = p.add_subparsers(dest="cmd")

    pt = sub.add_parser("target", help="生成目标组合 target_portfolio.json")
    pt.add_argument("--demo", action="store_true", help="用合成演示数据")
    pt.add_argument("--out", default="target_portfolio.json")

    pg = sub.add_parser("gen", help="生成某平台策略代码")
    pg.add_argument("--platform", required=True, choices=list(_ADAPTERS))
    pg.add_argument("--target", default="target_portfolio.json")
    pg.add_argument("--out", default=None, help="输出 .py 路径（默认 strategy_<platform>.py）")

    pp = sub.add_parser("paper", help="纸面回放演示")
    pp.add_argument("--demo", action="store_true")
    pp.add_argument("--target", default="target_portfolio.json")
    pp.add_argument("--days", type=int, default=120)

    args = p.parse_args()
    if args.cmd == "target":
        cands = _demo_candidates() if args.demo else _real_candidates()
        t = build_target(cands, source="demo" if args.demo else "selection")
        parent = os.path.dirname(args.out)
        if parent:
            os.makedirs(parent, exist_ok=True)
        save_target(t, args.out)
        wsum = round(sum(v["weight"] for v in t["positions"].values()), 3)
        print(f"[OK] 已生成 {args.out}：{len(t['positions'])} 个标的，仓位和={wsum}，缩放={t['scale']}")
    elif args.cmd == "gen":
        if not os.path.exists(args.target):
            print(f"[!] 未找到 {args.target}，先用 `target` 子命令生成")
            sys.exit(2)
        t = load_target(args.target)
        out = args.out or f"strategy_{args.platform}.py"
        parent = os.path.dirname(out)
        if parent:
            os.makedirs(parent, exist_ok=True)
        code = _ADAPTERS[args.platform].generate(t, path=out)
        print(f"[OK] 已生成 {args.platform} 策略：{out}（{len(code)} 字符，{len(t['positions'])} 标的）")
    elif args.cmd == "paper":
        if args.demo or not os.path.exists(args.target):
            t = build_target(_demo_candidates(), source="demo")
        else:
            t = load_target(args.target)
        prices = fetch_prices_demo(t, n_days=args.days)
        r = simulate(t, prices)
        print(json.dumps({k: r[k] for k in ("final_value", "total_return", "max_drawdown")},
                         ensure_ascii=False, indent=2))
        print(f"交易日: {len(r['nav'])}，成交笔数: {len(r['trades'])}")
    else:
        p.print_help()


if __name__ == "__main__":
    main()
