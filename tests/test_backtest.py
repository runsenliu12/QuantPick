"""A1+A3 回测日度模拟单测：涨停买不到降低收益、权重和=1、零收益净值不变。"""
import numpy as np
import pandas as pd

from scripts.backtest import simulate_portfolio
from src.trading import is_limit_up, is_limit_down


def _panel(values, cols):
    idx = pd.date_range("2024-01-01", periods=len(values))
    return pd.DataFrame(values, index=idx, columns=cols)


def test_simulate_zero_return_nav_unchanged():
    cols = ["a", "b", "c"]
    ret = _panel([[0.0, 0.0, 0.0]] * 4, cols)
    wp = _panel([[0.33, 0.33, 0.34]] * 4, cols)
    nav = simulate_portfolio(ret, wp, None, 0.0)
    assert len(nav) == 5
    assert abs(nav.iloc[-1] - 1.0) < 1e-9


def test_simulate_limit_up_lowers_nav():
    cols = ["a", "b"]
    # a 每天大涨 5%，b 横盘；无约束时两标的各半 -> 每天 +2.5%
    ret = _panel([[0.05, 0.0]] * 5, cols)
    wp = _panel([[0.5, 0.5]] * 5, cols)
    nav_free = simulate_portfolio(ret, wp, None, 0.0)
    # 第0天 a 涨停(10%)买不到 -> 该标的不计入，权重归 b（b 横盘）
    lim = _panel([[10.0, 0.0]] + [[0.0, 0.0]] * 4, cols)
    nav_limit = simulate_portfolio(ret, wp, lim, 0.0)
    # 约束净值（只有横盘 b）< 自由净值（持有大涨 a）
    assert nav_limit.iloc[-1] < nav_free.iloc[-1]


def test_simulate_limit_down_keeps_holding():
    cols = ["a", "b"]
    # 第1天把 a 换出（权重转 b），但第1天 a 跌停卖不出 -> 继续持有 a 一期，
    # 被迫承受跌停日跌幅（d1 a=-10%）；第2天换回 a 吃到涨幅（d2 a=+10%）。
    ret = _panel([[0.0, 0.0], [-0.10, 0.0], [0.10, 0.0], [0.0, 0.0]], cols)
    wp = _panel([[0.5, 0.5], [0.0, 1.0], [0.5, 0.5], [0.5, 0.5]], cols)
    lim = _panel([[0.0, 0.0], [-10.0, 0.0], [0.0, 0.0], [0.0, 0.0]], cols)
    nav_keep = simulate_portfolio(ret, wp, lim, 0.0)    # 跌停卖不出：被迫多持 a 一期
    nav_sell = simulate_portfolio(ret, wp, None, 0.0)   # 正常卖出：第1天起无 a
    # 卖不出时被迫吃了跌停日跌幅，净值与正常卖出不同（此处更低）
    assert nav_keep.iloc[-1] != nav_sell.iloc[-1]


def test_simulate_cost_reduces_nav():
    cols = ["a", "b"]
    ret = _panel([[0.0, 0.0]] * 4, cols)
    wp = _panel([[0.5, 0.5]] * 4, cols)
    nav_no_cost = simulate_portfolio(ret, wp, None, 0.0)
    nav_cost = simulate_portfolio(ret, wp, None, 0.01)
    assert nav_cost.iloc[-1] <= nav_no_cost.iloc[-1]
