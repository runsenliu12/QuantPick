"""多周期共振。

思路：不同周期（如 5/20/60 日）的均线同向排列时，趋势确定性更高。
  - 多头排列：短周期均线 > 中 > 长 -> 看多
  - 空头排列：短 < 中 < 长 -> 看空
  - 否则观望
比单一均线更抗噪，但信号更滞后。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import sma


def multi_timeframe_signal(close, windows=(5, 20, 60), long_only: bool = True):
    """多周期均线共振信号。

    windows: 由短到长的均线窗口元组（至少 2 个）。
    返回：{-1,0,+1} 信号序列。
    """
    if len(windows) < 2:
        raise ValueError("windows 至少需 2 个周期")
    mas = {w: sma(close, w) for w in windows}
    up = True
    down = True
    for k in range(len(windows) - 1):
        up = up & (mas[windows[k]] > mas[windows[k + 1]])
        down = down & (mas[windows[k]] < mas[windows[k + 1]])
    sig = np.where(up, 1, np.where(down, -1, 0))
    return pd.Series(sig, index=close.index)
