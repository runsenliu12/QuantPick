"""趋势跟踪类方法。

核心假设：价格沿趋势运行，均线/突破能捕捉方向。
主要风险：震荡市频繁假突破，需用波动率过滤与移动止损配合。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import sma, ema


def dual_ma_signal(close: pd.Series, fast: int = 5, slow: int = 20) -> pd.Series:
    """双均线交叉：快线上穿慢线看多(+1)，下穿看空(-1)，无交叉时沿用前值。

    适用：中长趋势行情；不适：横盘。常见参数 fast=5/slow=20 或 10/60。
    """
    f, s = sma(close, fast), sma(close, slow)
    cross = np.sign(f - s)
    return cross.ffill().fillna(0)


def triple_ma_signal(close, fast: int = 5, mid: int = 20, slow: int = 60):
    """三均线：快>中>慢 强多(+1)；快<中<慢 强空(-1)；其余 0。

    比双均线更少假信号，但信号更滞后。
    """
    f, m, s = sma(close, fast), sma(close, mid), sma(close, slow)
    long = (f > m) & (m > s)
    short = (f < m) & (m < s)
    return pd.Series(np.where(long, 1, np.where(short, -1, 0)), index=close.index)


def macd_signal(close, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD：DIF 上穿 DEA 看多(+1)，下穿看空(-1)，无交叉沿用前值。"""
    dif = ema(close, fast) - ema(close, slow)
    dea = ema(dif, signal)
    cross = np.sign(dif - dea)
    return cross.ffill().fillna(0)


def breakout_signal(close, window: int = 20):
    """N 日高点突破：收盘价创 window 日新高看多(+1)，否则 0（用昨日前高避免未来函数）。

    适用：突破行情（如海龟法则的 20 日突破）；需配合 ATR 止损。
    """
    hh = close.rolling(window, min_periods=window).max().shift(1)
    return pd.Series(np.where(close > hh, 1, 0), index=close.index)
