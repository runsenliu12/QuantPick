"""波动率类方法：ATR 与波动率目标。

不直接给方向，而是用于止损距离设定、仓位缩放，常与其他信号组合使用。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import rolling_std


def atr(high, low, close, window: int = 14):
    """真实波幅均值（ATR），常用于移动止损距离与头寸缩放。"""
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window, min_periods=1).mean()


def vol_target_weight(returns: pd.Series, target_vol: float = 0.15,
                      window: int = 60, cap: float = 1.0):
    """波动率目标权重：历史波动越高仓位越低，使组合年化波动逼近 target_vol。

    returns 为日收益序列；结果按 cap 截断（cap=1 即满仓上限）。
    """
    realized = rolling_std(returns, window) * np.sqrt(252)
    w = target_vol / realized.replace(0, np.nan)
    return w.clip(upper=cap).fillna(0.0)
