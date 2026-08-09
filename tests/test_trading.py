"""A1 交易约束单测：涨停买不到、跌停卖不出、停牌顺延、流动性冲击。"""
import pandas as pd
import numpy as np

from src.trading import resolve_entry, resolve_exit, is_limit_up, is_limit_down, liquidity_slippage


def _hist(closes, pcts):
    return pd.DataFrame(
        {"收盘": closes, "涨跌幅": pcts},
        index=pd.date_range("2024-01-01", periods=len(closes)),
    )


def test_is_limit_up_down():
    s = pd.Series([9.8, -9.9, 0.0, 10.2])
    assert is_limit_up(s).tolist() == [True, False, False, True]
    assert is_limit_down(s).tolist() == [False, True, False, False]


def test_resolve_entry_skips_limit_up():
    # 第0天涨停(10.0)买不到，顺延到第1天(5.0)可买
    h = _hist([10.0, 5.0, 4.0], [10.0, 1.0, -1.0])
    res = resolve_entry(h, 0)
    assert res is not None
    assert res[0] == 1 and res[1] == 5.0


def test_resolve_entry_all_limit_returns_none():
    # 连续涨停，窗口内都买不到
    h = _hist([1.0, 2.0, 3.0], [10.0, 10.0, 10.0])
    assert resolve_entry(h, 0) is None


def test_resolve_exit_skips_limit_down():
    # 第1天跌停(-10.0)卖不出，顺延到第2天(11.0)
    h = _hist([10.0, 9.0, 11.0], [-1.0, -10.0, 2.0])
    res = resolve_exit(h, 1)
    assert res is not None
    assert res[0] == 2 and res[1] == 11.0


def test_resolve_handles_suspension():
    # 第0天 NaN（停牌）顺延到第1天
    h = _hist([np.nan, 5.0, 6.0], [np.nan, 1.0, 2.0])
    res = resolve_entry(h, 0)
    assert res is not None
    assert res[0] == 1


def test_liquidity_slippage():
    assert liquidity_slippage(1e8) == 0.0
    assert liquidity_slippage(1e5) == 0.003
    assert liquidity_slippage(None) == 0.0
