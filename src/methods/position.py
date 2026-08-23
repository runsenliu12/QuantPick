"""仓位管理类方法。

决定「买多少」比「买什么」更影响长期存活率。下面是不依赖回测数据的解析公式。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import normalize_weights


def kelly_fraction(win_rate: float, payoff: float, frac: float = 1.0):
    """凯利公式：f* = (p*b - q)/b，frac<1 为半凯利以降低波动。

    win_rate: 胜率 p；payoff: 盈亏比 b（平均盈利/平均亏损）；返回单笔下注比例 [0,1]。
    """
    q = 1 - win_rate
    f = (win_rate * payoff - q) / payoff if payoff > 0 else 0.0
    return max(0.0, min(1.0, f)) * frac


def fixed_fraction(capital: float, risk_per_trade: float,
                   stop_distance: float, price: float):
    """固定分数法：每笔风险 = 资金*risk_per_trade，仓位 = 风险/(止损距离*价格)。"""
    risk_amt = capital * risk_per_trade
    denom = stop_distance * price
    return risk_amt / denom if denom > 0 else 0.0


def risk_parity_weights(cov: pd.DataFrame):
    """风险平价：迭代求解使各资产边际风险贡献相等的权重（合计为 1）。

    cov 为资产协方差矩阵。与 src/risk.py 思路一致，此处为独立通用实现。
    """
    n = cov.shape[0]
    w = np.repeat(1.0 / n, n)
    for _ in range(50):
        w = w / w.sum()
        cov_w = cov @ w
        mrc = cov_w * w
        w = w * (1.0 / (mrc + 1e-9))
        w = w / w.sum()
    return pd.Series(w, index=cov.index)
