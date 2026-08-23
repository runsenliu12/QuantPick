"""动量类方法。

核心假设：过去表现强的资产短期会延续（反应不足）。
主要风险：动量崩溃（反转）常见于情绪拐点与极端估值。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def momentum_signal(close, window: int = 60):
    """时间序列动量：过去 window 日收益为正看多(+1)，负看空(-1)。

    常用 window=60（约一季度）或 12 个月动量（跨月调仓）。
    """
    mom = close / close.shift(window) - 1
    return pd.Series(np.sign(mom.fillna(0)), index=close.index)


def cross_sectional_momentum(returns: pd.DataFrame, window: int = 60):
    """横截面动量：每个时点对资产按过去收益排序，前 1/3 做多(+1)、后 1/3 做空(-1)，中间 0。

    returns 为宽表（行=日期，列=资产）。多空组合可对冲市场 beta。
    """
    roll = returns.rolling(window).sum()
    rank = roll.rank(axis=1, pct=True)
    out = pd.DataFrame(0.0, index=roll.index, columns=roll.columns)
    out[rank >= 2 / 3] = 1
    out[rank <= 1 / 3] = -1
    return out
