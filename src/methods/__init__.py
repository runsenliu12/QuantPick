"""常见量化方法代码库（QuantPick methods）。

纯函数实现，不连接数据源/券商，可直接 import 用于研究或作为策略模板。
包含：
  - base              : 公共工具（收益、均线、z-score、权重归一、信号转持仓）
  - trend             : 趋势跟踪（双均线、三均线、MACD、突破）
  - momentum          : 动量（时间序列、横截面）
  - mean_reversion    : 均值回归（z-score、布林带、RSI）
  - volatility        : 波动率（ATR、波动率目标）
  - stat_arb          : 统计套利（配对交易、网格）
  - position          : 仓位管理（凯利、固定分数、风险平价）
  - multi_factor      : 多因子合成

所有方法仅依赖 numpy / pandas，无外部网络/IO。调用示例：

    from src.methods import trend
    sig = trend.dual_ma_signal(close, fast=5, slow=20)
"""
from . import (trend, momentum, mean_reversion, volatility,
               stat_arb, position, multi_factor)
from .base import (to_returns, log_returns, sma, ema, rolling_std, zscore,
                   normalize_weights, signal_to_position)

__all__ = [
    "trend", "momentum", "mean_reversion", "volatility",
    "stat_arb", "position", "multi_factor",
    "to_returns", "log_returns", "sma", "ema", "rolling_std",
    "zscore", "normalize_weights", "signal_to_position",
]
