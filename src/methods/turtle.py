"""海龟法则完整版（Turtle Trading Rules）。

经典趋势跟踪系统，核心要素：
  - 入场：价格突破 N 日（默认 20）最高/最低
  - 加仓：每向有利方向移动 0.5*ATR 加一单位，最多 max_units 单位（金字塔）
  - 止损：2*ATR 反向止损（追踪）
  - 退出：多单跌破 10 日最低 / 空单突破 10 日最高（或用 55 日系统）
  - 仓位：unit = 风险预算 / (ATR * 合约乘数)，此处返回单位数，金额权重另算

实现为状态机（逐根 K 线推进）。返回 position 为单位数（long_only 时 >=0）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .volatility import atr


def turtle_signal(high, low, close, entry: int = 20, exit_win: int = 10,
                  atr_win: int = 20, add_unit: float = 0.5, max_units: int = 4,
                  long_only: bool = False):
    """海龟法则完整版信号。

    参数：
      entry     : 突破入场窗口（唐奇安通道）
      exit_win  : 退出窗口（反向突破）
      atr_win   : ATR 窗口（止损/加仓距离）
      add_unit  : 加仓步长（单位：ATR）
      max_units : 最大持仓单位数
      long_only : True 时不做空
    返回：position 序列，取值 [-max_units, +max_units] 整数单位。
    """
    a = atr(high, low, close, atr_win)
    hh = close.rolling(entry, min_periods=entry).max().shift(1)
    ll = close.rolling(entry, min_periods=entry).min().shift(1)
    ex_h = close.rolling(exit_win, min_periods=exit_win).max().shift(1)
    ex_l = close.rolling(exit_win, min_periods=exit_win).min().shift(1)

    pos = [0.0] * len(close)
    ep = 0.0  # 最近一次入场/加仓基准价
    for i in range(1, len(close)):
        p, av = close.iloc[i], a.iloc[i]
        prev = pos[i - 1]
        if av != av or av <= 0:  # ATR 缺失/为 0 时观望
            pos[i] = prev
            continue
        if prev == 0:
            if p > hh.iloc[i]:
                prev, ep = 1, p
            elif (not long_only) and p < ll.iloc[i]:
                prev, ep = -1, p
        else:
            if prev > 0:
                if p >= ep + add_unit * av and prev < max_units:
                    prev, ep = prev + 1, p          # 金字塔加仓
                elif p < ep - 2 * av:
                    prev = 0                          # ATR 止损
                elif p < ex_l.iloc[i]:
                    prev = 0                          # 反向突破退出
            else:  # prev < 0
                if p <= ep - add_unit * av and prev > -max_units:
                    prev, ep = prev - 1, p
                elif p > ep + 2 * av:
                    prev = 0
                elif p > ex_h.iloc[i]:
                    prev = 0
        pos[i] = prev
    return pd.Series(pos, index=close.index)


def turtle_unit_size(capital: float, price: float, atr_val: float,
                     risk_frac: float = 0.01, multiplier: float = 1.0):
    """海龟单位金额权重：每单位风险 = 账户*risk_frac，故单位股数 = 风险/（ATR*乘数*价）。

    返回每单位股数（float）；实际下单取整到交易单位。
    """
    if atr_val <= 0 or price <= 0:
        return 0.0
    dollar_risk = capital * risk_frac
    return dollar_risk / (atr_val * multiplier * price)
