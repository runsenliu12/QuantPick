"""执行层 CLI：目标组合生成 / 三平台策略代码生成 / 纸面回放。

用法（项目根目录下）：
    python -m scripts.execute target --demo            # 生成 target_portfolio.json（演示数据）
    python -m scripts.execute target                   # 生成（真实选股，需联网/缓存）
    python -m scripts.execute gen --platform ptrade     # 生成 PTrade 策略文件
    python -m scripts.execute gen --platform qmt --out strategy_qmt.py
    python -m scripts.execute gen --platform joinquant
    python -m scripts.execute paper --demo             # 纸面回放演示（合成行情）
    python -m scripts.execute method --name turtle --demo   # 把方法接到单标的回测（合成数据）
    python -m scripts.execute method --name rsi --params "window=14,oversold=30" --n 300
    python -m scripts.execute rotate --assets 8 --top-k 2   # 多标的 ETF 动量轮动回测
    python -m scripts.execute rotate --trend-amp 0          # 无趋势场景，演示轮动失效

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
from src.methods.backtest_signal import backtest_method, list_methods
from src.methods import rotation as _rotation

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

    pm = sub.add_parser("method", help="把某个量化方法接到单标的回测框架（合成数据演示，不连券商）")
    pm.add_argument("--name", required=True, help="方法名，如 turtle / dual_ma / rsi / breakout")
    pm.add_argument("--params", default="", help="覆盖参数，如 entry=20,exit_win=10,fast=5")
    pm.add_argument("--n", type=int, default=250, help="合成 K 线数量")
    pm.add_argument("--seed", type=int, default=7, help="随机种子（换种子换行情）")
    pm.add_argument("--cost", type=float, default=0.0008, help="单边成本（佣金+滑点）")
    pm.add_argument("--no-t1", action="store_true", help="关闭 T+1（信号当日生效）")
    pm.add_argument("--list", action="store_true", help="列出所有支持的方法名")

    pr = sub.add_parser("rotate", help="多标的 ETF 动量轮动回测（合成数据演示，不连券商）")
    pr.add_argument("--n", type=int, default=750, help="合成交易日数量")
    pr.add_argument("--assets", type=int, default=8, help="标的池数量")
    pr.add_argument("--seed", type=int, default=7, help="随机种子")
    pr.add_argument("--top-k", type=int, default=2, help="持有动量最强的几个标的")
    pr.add_argument("--lookback", type=int, default=21, help="动量窗口")
    pr.add_argument("--cost", type=float, default=0.0005, help="单边成本（佣金+滑点）")
    pr.add_argument("--trend-amp", type=float, default=0.0015,
                    help="合成行情的趋势强度；设为 0 得到无趋势随机游走（演示轮动失效场景）")

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
    elif args.cmd == "method":
        if args.list:
            print("支持的方法：", ", ".join(list_methods()))
            return
        params = {}
        for kv in (s for s in args.params.split(",") if s.strip()):
            k, v = kv.split("=", 1)
            try:
                vv = int(v)
            except ValueError:
                try:
                    vv = float(v)
                except ValueError:
                    vv = v
            params[k.strip()] = vv
        res = backtest_method(args.name, params=params, n=args.n, seed=args.seed,
                              cost=args.cost, t1=not args.no_t1)
        m = res["metrics"]
        print(f"=== 方法 {args.name} 回测（合成数据，不连券商） ===")
        print(f"参数: {params or '默认'}  T+1: {not args.no_t1}  成本: {args.cost}  种子: {args.seed}")
        for k, v in m.items():
            if isinstance(v, float):
                print(f"  {k}: {v:.4f}" if abs(v) < 1 else f"  {k}: {v:.2f}")
            else:
                print(f"  {k}: {v}")
    elif args.cmd == "rotate":
        px = _rotation.gen_multi_prices(n=args.n, n_assets=args.assets, seed=args.seed,
                                        trend_amp=args.trend_amp)
        print(f"=== ETF 动量轮动回测（合成数据，不连券商） ===")
        print(f"标的池: {args.assets} 个  交易日: {args.n}  种子: {args.seed}  "
              f"趋势强度: {args.trend_amp}  成本: {args.cost}")
        print()
        rows = []
        for tk in (1, 2, 3):
            if tk > args.assets:
                continue
            r = _rotation.rotation_backtest(px, lookback=args.lookback, top_k=tk, cost=args.cost)
            m = r["metrics"]
            rows.append((f"动量轮动 top{tk}", m, r["total_turnover"], r["num_switches"]))
        bh = _rotation.buy_and_hold(px)
        mb = _rotation.compute_nav_metrics(bh)
        rows.append(("等权买入持有(基准)", mb, 0.0, 0))

        print(f"{'策略':<20}{'总收益':>10}{'年化':>10}{'Sharpe':>9}{'最大回撤':>10}{'换手':>9}{'调仓':>7}")
        print("-" * 75)
        for name, m, turn, sw in rows:
            print(f"{name:<20}{m['total_return']:>10.3f}{m['annual_return']:>10.3f}"
                  f"{m['sharpe']:>9.3f}{m['max_drawdown']:>10.3f}{turn:>9.1f}{sw:>7}")
        print()
        if args.trend_amp == 0:
            print("提示：trend-amp=0 -> 无趋势随机游走，动量无信号可捕捉，")
            print("      轮动只贡献换手成本，通常跑输买入持有。这是轮动策略的失效场景。")
        else:
            print("提示：合成数据含持续轮动趋势，动量轮动通常占优；")
            print("      真实市场趋势强弱随环境变化，务必做样本外与多参数稳健性检验。")
    else:
        p.print_help()


if __name__ == "__main__":
    main()
