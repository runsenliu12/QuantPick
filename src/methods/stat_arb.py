"""统计套利类方法：配对交易与网格。

配对交易依赖两资产长期协整；非协整时信号失效，需先做协整检验（如 ADF）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import sma, rolling_std


def coint_zscore(price_a, price_b, window: int = 60, entry: float = 2.0,
                 exit_z: float = 0.5, long_only: bool = False):
    """配对交易：对价差（对数比）做 z-score，偏离极端时反向开仓。

    价差是 log(A)-log(B)。z>entry 表示 A 相对 B 偏贵 -> 做空 A 做多 B（净 -1）；
    z<-entry 表示 A 偏便宜 -> 做多 A 做空 B（净 +1）；回到 ±exit_z 平仓。
    """
    spread = np.log(price_a) - np.log(price_b)
    m = sma(spread, window)
    s = rolling_std(spread, window)
    z = (spread - m) / s.replace(0, np.nan)
    pos = [0.0] * len(z)
    for i in range(1, len(z)):
        prev = pos[i - 1]
        zv = z.iloc[i]
        if prev == 0:
            if zv > entry:
                prev = -1 if not long_only else 0
            elif zv < -entry:
                prev = 1
        else:
            if abs(zv) < exit_z:
                prev = 0
        pos[i] = prev
    return pd.Series(pos, index=spread.index)


def grid_levels(price, n: int = 10, step_pct: float = 0.02):
    """生成网格价位：以 price 为中心，上下各 n 档，间隔 step_pct。

    返回排序后的价位列表，供网格交易回测/下单使用。
    """
    levels = [price * (1 + (i - n) * step_pct) for i in range(2 * n + 1)]
    return sorted(levels)
