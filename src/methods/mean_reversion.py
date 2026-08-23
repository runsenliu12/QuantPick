"""均值回归类方法。

核心假设：价格偏离均值后会回归。
主要风险：趋势市中「接飞刀」会持续亏损，前提是均值/协整关系真实存在。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import sma, rolling_std, zscore


def zscore_reversion(close, window: int = 20, entry: float = 2.0,
                     exit_z: float = 0.5, long_only: bool = False):
    """z-score 回归：偏离超过 +entry 做空、-entry 做多，回到 ±exit_z 平仓（状态机）。"""
    z = zscore(close, window)
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
    return pd.Series(pos, index=close.index)


def bollinger_signal(close, window: int = 20, k: float = 2.0, long_only: bool = False):
    """布林带：触及下轨做多、上轨做空，回到中轨平仓。"""
    mid = sma(close, window)
    sd = rolling_std(close, window)
    up, lo = mid + k * sd, mid - k * sd
    pos = [0.0] * len(close)
    for i in range(1, len(close)):
        prev = pos[i - 1]
        p, u, l, m = close.iloc[i], up.iloc[i], lo.iloc[i], mid.iloc[i]
        if prev == 0:
            if p <= l:
                prev = 1
            elif (not long_only) and p >= u:
                prev = -1
        else:
            if (prev > 0 and p >= m) or (prev < 0 and p <= m):
                prev = 0
        pos[i] = prev
    return pd.Series(pos, index=close.index)


def rsi_signal(close, window: int = 14, overbought: int = 70, oversold: int = 30,
               long_only: bool = True):
    """RSI 超买超卖：超卖做多、超买卖出（long_only 时只做多，回到 50 平仓）。"""
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = -delta.clip(upper=0).rolling(window).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    pos = [0.0] * len(close)
    for i in range(1, len(close)):
        prev = pos[i - 1]
        r = rsi.iloc[i]
        if prev == 0:
            if r < oversold:
                prev = 1
            elif (not long_only) and r > overbought:
                prev = -1
        else:
            if (prev > 0 and r > 50) or (prev < 0 and r < 50):
                prev = 0
        pos[i] = prev
    return pd.Series(pos, index=close.index)
