"""纸面执行模拟器：在不连接任何券商的前提下，回放目标组合的历史表现。

模拟逻辑贴近券商行为：
- 每日再平衡到目标权重（order_target_value 语义）
- 自适应止损：价格跌破建仓成本 ×(1-stop_loss) 时清仓
- 涨停买不到 / 跌停卖不出（复用 src.trading 真实约束）
- T+1：当日买入的份额当日不可卖
- 双边成本（佣金+滑点，默认 0.1%）

输入：target（build_target 产物）+ prices（{code: 收盘价 Series}）
输出：{nav, trades, final_value, total_return, max_drawdown}
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.trading import is_limit_up, is_limit_down


def fetch_prices_demo(target: dict, n_days: int = 120, seed: int = 42) -> dict:
    """生成合成价格序列（离线演示，无需网络）。"""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n_days, freq="B")
    prices = {}
    for i, (code, info) in enumerate(target["positions"].items()):
        base = 10.0 if info["kind"] == "stock" else 1.0
        r = rng.normal(0.0005, 0.02, n_days)
        px = base * np.cumprod(1 + r)
        prices[code] = pd.Series(px, index=dates)
    return prices


def simulate(target: dict, prices: dict, cost_rate: float = 0.001,
             initial: float = 1.0) -> dict:
    positions = target.get("positions", {})
    codes = list(positions.keys())
    series = {c: prices.get(c) for c in codes if prices.get(c) is not None}
    if not series:
        return {"nav": [], "trades": [], "final_value": initial,
                "total_return": 0.0, "max_drawdown": 0.0, "error": "no price data"}
    df = pd.DataFrame(series).dropna(how="all").sort_index()
    if df.empty:
        return {"nav": [], "trades": [], "final_value": initial,
                "total_return": 0.0, "max_drawdown": 0.0, "error": "no price data"}

    pct = df.pct_change().fillna(0.0) * 100.0
    cash = float(initial)
    shares = {c: 0.0 for c in codes}
    entry = {c: 0.0 for c in codes}
    buy_day = {c: -999 for c in codes}
    nav, trades = [], []

    def mv(closes):
        return cash + sum(shares[c] * closes[c] for c in codes if pd.notna(closes[c]))

    for t in range(len(df)):
        closes = df.iloc[t]
        cur_pct = pct.iloc[t]

        # 1) 自适应止损（先卖）
        for c in codes:
            if shares[c] > 0 and entry[c] > 0 and pd.notna(closes[c]):
                if closes[c] <= entry[c] * (1 - positions[c]["stop_loss"]):
                    if not is_limit_down(cur_pct[c]) and buy_day[c] < t:
                        proceeds = shares[c] * closes[c]
                        fee = proceeds * cost_rate
                        cash += proceeds - fee
                        trades.append((t, c, "stop", round(float(closes[c]), 3)))
                        shares[c] = 0.0
                        entry[c] = 0.0

        # 2) 再平衡（买/卖到目标权重）
        total = mv(closes)
        for c in codes:
            if pd.isna(closes[c]):
                continue
            desired = total * positions[c]["weight"]
            cur = shares[c] * closes[c]
            diff = desired - cur
            if diff > 1e-6:
                if is_limit_up(cur_pct[c]):
                    continue
                cost = diff
                fee = cost * cost_rate
                if cost + fee <= cash + 1e-9:
                    shares[c] += cost / closes[c]
                    cash -= cost + fee
                    entry[c] = float(closes[c])
                    buy_day[c] = t
                    trades.append((t, c, "buy", round(float(closes[c]), 3)))
            elif diff < -1e-6:
                if is_limit_down(cur_pct[c]) or buy_day[c] == t:
                    continue
                proceeds = -diff
                fee = proceeds * cost_rate
                shares[c] -= proceeds / closes[c]
                cash += proceeds - fee
                trades.append((t, c, "sell", round(float(closes[c]), 3)))

        nav.append((df.index[t], mv(closes)))

    navdf = pd.Series({d: v for d, v in nav})
    maxdd = 0.0
    if len(navdf) > 1:
        peak = navdf.cummax()
        maxdd = float(((peak - navdf) / peak).max())

    return {
        "nav": [{"date": str(d)[:10], "value": round(float(v), 4)} for d, v in navdf.items()],
        "trades": [{"day": t, "code": c, "action": a, "price": p} for t, c, a, p in trades],
        "final_value": round(float(navdf.iloc[-1]), 4),
        "total_return": round(float(navdf.iloc[-1] / initial - 1), 4),
        "max_drawdown": round(maxdd, 4),
    }
