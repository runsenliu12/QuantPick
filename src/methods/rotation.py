"""ETF / 多标的动量轮动（改写自聚宽社区策略「指数ETF动量轮动策略-2」）。

原始策略（`joinquant/18_etf_index_momentum.py`，作者：野蛮生涨）的核心逻辑：
  1. 在跨市场 ETF 池（A股宽基 / 海外 / 商品）中，计算每个标的的 **21 日平滑动量**：
     R = (近3日均价 - 21日前3日均价) / 21日前3日均价
     （用 3 日均线平滑，避免单日涨跌过大导致频繁换仓）
  2. 按 R 降序排名，取动量最强的标的；
  3. **绝对动量过滤**：只有当动量 > 0（价格高于基准价）才持有，否则空仓；
     换仓有 ±0.1% 的缓冲区，避免来回打脸。

本模块把它抽象成不依赖聚宽 API 的纯函数，可直接接回测框架：

    from src.methods.rotation import momentum_score, rotation_weights, rotation_backtest
    score = momentum_score(prices, lookback=21, smooth=3)
    w     = rotation_weights(prices, top_k=1, threshold=0.0)
    res   = rotation_backtest(prices, top_k=2, cost=0.0005)

`prices` 为 DataFrame（行=日期，列=标的）的收盘价。全程无未来函数：
t 时刻的打分只用 t 及之前的数据，且默认 T+1 生效（次日才开始承担涨跌）。

不连接任何数据源 / 券商；仅为方法模板。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def momentum_score(prices, lookback: int = 21, smooth: int = 3):
    """平滑动量：近 smooth 日均价 相对 lookback 日前的 smooth 日均价 的涨幅。

    返回与 prices 同形状的 DataFrame，前 lookback+smooth-1 行为 NaN。
    """
    prices = pd.DataFrame(prices)
    recent = prices.rolling(smooth).mean()
    base = prices.shift(lookback).rolling(smooth).mean()
    return recent / base - 1.0


def rotation_weights(prices, lookback: int = 21, smooth: int = 3,
                     top_k: int = 1, threshold: float = 0.0):
    """按动量排名生成目标权重。

    top_k     : 持有动量最强的几个标的（默认 1，即原策略的「只买最靓的仔」）
    threshold : 绝对动量阈值，最强动量 <= threshold 时全部空仓（原策略为 0）
    返回权重 DataFrame，每行和为 1（持仓）或 0（空仓）。
    """
    prices = pd.DataFrame(prices)
    score = momentum_score(prices, lookback=lookback, smooth=smooth)
    w = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)

    for t in range(len(prices)):
        s = score.iloc[t].dropna()
        if s.empty:
            continue
        s = s[s > threshold]
        if s.empty:
            continue
        picks = s.sort_values(ascending=False).head(top_k).index
        w.iloc[t, w.columns.get_indexer(picks)] = 1.0 / len(picks)
    return w


def rotation_backtest(prices, lookback: int = 21, smooth: int = 3,
                      top_k: int = 1, threshold: float = 0.0,
                      cost: float = 0.0005, t1: bool = True,
                      init_capital: float = 1.0) -> dict:
    """多标的动量轮动回测（T+1 + 按换手扣成本）。

    cost : 单边成本（佣金+滑点），按组合总换手率计
    t1   : 权重次日生效，避免用当日收盘价打分又吃当日收益
    返回 nav / 权重 / 换手 / 调仓次数 / 指标。
    """
    prices = pd.DataFrame(prices)
    if prices.shape[1] < 2:
        raise ValueError("动量轮动至少需要 2 个标的")

    w = rotation_weights(prices, lookback=lookback, smooth=smooth,
                         top_k=top_k, threshold=threshold)
    eff = w.shift(1) if t1 else w
    eff = eff.fillna(0.0)

    eff_v = eff.to_numpy(dtype=float)
    ret_v = prices.pct_change().fillna(0.0).to_numpy(dtype=float)

    nav = [float(init_capital)]
    total_turn = 0.0
    prev_w = eff_v[0]

    for i in range(1, len(prices)):
        e = eff_v[i]
        turn = float(np.nansum(np.abs(e - prev_w)))
        if turn > 0:
            nav[-1] *= (1 - cost * turn)
            total_turn += turn
        day_ret = float(np.nansum(prev_w * ret_v[i]))
        nav.append(nav[-1] * (1 + day_ret))
        prev_w = e

    nav = pd.Series(nav, index=prices.index)

    # 调仓次数：权重非零集合发生变化的次数
    holdings = [tuple(np.flatnonzero(row > 0)) for row in eff_v]
    switches = sum(1 for i in range(1, len(holdings)) if holdings[i] != holdings[i - 1])

    return {
        "nav": nav,
        "weights": w,
        "eff_weights": eff,
        "total_turnover": float(total_turn),
        "num_switches": int(switches),
        "metrics": compute_nav_metrics(nav, total_turnover=total_turn),
    }


def buy_and_hold(prices, cost: float = 0.0) -> pd.Series:
    """等权买入持有基准（只在首日建仓，之后不再调仓）。"""
    prices = pd.DataFrame(prices)
    n_assets = prices.shape[1]
    w0 = np.full(n_assets, 1.0 / n_assets)
    ret_v = prices.pct_change().fillna(0.0).to_numpy(dtype=float)
    nav = [1.0 - cost]
    for i in range(1, len(prices)):
        nav.append(nav[-1] * (1 + float(np.nansum(w0 * ret_v[i]))))
    return pd.Series(nav, index=prices.index)


def compute_nav_metrics(nav, total_turnover: float = 0.0) -> dict:
    """净值曲线绩效指标（与 backtest_signal.compute_signal_metrics 口径一致）。"""
    nav = pd.Series(nav).reset_index(drop=True).dropna()
    if len(nav) < 2:
        return {}
    rets = nav.pct_change().dropna()
    total = float(nav.iloc[-1] - 1)
    years = (len(nav) - 1) / 252.0
    ann = (1 + total) ** (1 / years) - 1 if years > 0 else 0.0
    sharpe = float(rets.mean() / rets.std() * np.sqrt(252)) if rets.std() > 0 else 0.0
    mdd = float((nav / nav.cummax() - 1).min())
    return {
        "total_return": total,
        "annual_return": float(ann),
        "sharpe": sharpe,
        "max_drawdown": mdd,
        "vol_annual": float(rets.std() * np.sqrt(252)),
        "total_turnover": float(total_turnover),
    }


def gen_multi_prices(n: int = 750, n_assets: int = 8, seed: int = 7,
                     vol: float = 0.010, drift: float = 0.0002,
                     trend_amp: float = 0.0015, trend_period: int = 250):
    """合成多标的行情用于离线演示，不连接任何数据源。

    每个标的的漂移按正弦缓慢变化（周期 trend_period，相位错开），模拟
    **风格/行业轮动**：任一时刻总有部分标的处于上升趋势、另一部分下行。
    这样动量轮动才有可捕捉的相对强弱。

    trend_amp=0 时退化为无趋势的纯随机游走 —— 这正是动量策略的失效场景
    （频繁换仓只贡献成本），可用于演示「什么时候不该用轮动」。
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2023-01-01", periods=n, freq="B")
    phase = rng.uniform(0, 2 * np.pi, n_assets)
    phase[0] = 0.0

    rets = np.zeros((n, n_assets))
    for i in range(n):
        d = drift + trend_amp * np.sin(2 * np.pi * i / trend_period + phase)
        rets[i] = d + rng.normal(0, vol, n_assets)

    return pd.DataFrame(100.0 * np.cumprod(1 + rets, axis=0),
                        index=dates,
                        columns=[f"ETF{i+1:02d}" for i in range(n_assets)])
