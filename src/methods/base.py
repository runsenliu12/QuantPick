"""量化方法公共工具。

所有方法均为纯函数，只接受价格/收益序列（pandas）并返回信号或权重，
不连接任何数据源、不调用券商接口、不落盘。可在研究环境直接 import 使用。
约定：
  - 信号 signal 取值 {-1, 0, +1}（空/空仓 / 多 / 空）
  - 持仓 position 取值  [0,  +1]（long_only 时）或 [-1, +1]（多空）
  - 权重 weight    取值  >= 0，合计为 1（组合层面）
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def to_returns(close: pd.Series) -> pd.Series:
    """简单收益率序列（百分比变化）。"""
    return close.pct_change().fillna(0.0)


def log_returns(close: pd.Series) -> pd.Series:
    """对数收益率序列。"""
    return np.log(close / close.shift(1)).fillna(0.0)


def sma(series: pd.Series, window: int) -> pd.Series:
    """简单移动平均，不足窗口时用半数样本起算。"""
    return series.rolling(window, min_periods=max(1, window // 2)).mean()


def ema(series: pd.Series, span: int) -> pd.Series:
    """指数移动平均。"""
    return series.ewm(span=span, adjust=False).mean()


def rolling_std(series: pd.Series, window: int) -> pd.Series:
    """滚动标准差。"""
    return series.rolling(window, min_periods=max(1, window // 2)).std()


def zscore(series: pd.Series, window: int) -> pd.Series:
    """滚动 z-score：相对窗口均值的标准化偏离。"""
    m = sma(series, window)
    s = rolling_std(series, window)
    return (series - m) / s.replace(0, np.nan)


def rolling_corr(a: pd.Series, b: pd.Series, window: int) -> pd.Series:
    """两序列滚动相关系数。"""
    return a.rolling(window).corr(b)


def normalize_weights(weights: pd.Series) -> pd.Series:
    """权重归一化到合计为 1（全为 0 时退化为等权）。"""
    s = weights.sum()
    if s <= 0 or np.isnan(s):
        return pd.Series(1.0 / len(weights), index=weights.index)
    return weights / s


def signal_to_position(signal: pd.Series, long_only: bool = True) -> pd.Series:
    """把 {-1,0,1} 信号转成持仓：long_only 时把 -1 置 0。"""
    pos = signal.clip(-1, 1)
    if long_only:
        pos = pos.clip(lower=0)
    return pos
