"""tests: src/methods/rotation.py —— 多标的 ETF 动量轮动。

重点验证三件事：
  1. 无未来函数（打分只用当期及之前的数据）
  2. 权重结构正确（行和为 0 或 1；top_k 生效；绝对动量过滤生效）
  3. 回测口径（净值起点、换手、T+1）与「何时有效/何时失效」的定性结论
"""
import numpy as np
import pandas as pd
import pytest

from src.methods import rotation


def _ramp(n=120, k=4, start=100.0, step=1.0):
    """每期固定上涨的价格面板（动量恒为正）。"""
    idx = pd.date_range("2023-01-01", periods=n, freq="B")
    data = {f"A{i}": start * (1 + 0.001 * i) + step * np.arange(n) for i in range(k)}
    return pd.DataFrame(data, index=idx)


def _falling(n=120, k=4):
    """每期固定下跌的价格面板（动量恒为负 -> 应全部空仓）。"""
    idx = pd.date_range("2023-01-01", periods=n, freq="B")
    data = {f"A{i}": 200.0 - 0.5 * np.arange(n) - i for i in range(k)}
    return pd.DataFrame(data, index=idx)


# ---- 1. 无未来函数 ----

def test_momentum_score_has_no_lookahead():
    prices = _ramp(n=120)
    score = rotation.momentum_score(prices, lookback=21, smooth=3)
    # 改掉最后一行的价格，不应影响之前任何一行的打分
    t = prices.index[-1]
    t_prev = prices.index[-2]
    before = score.loc[t_prev].copy()
    prices.loc[t, "A0"] = 99999.0
    after = rotation.momentum_score(prices, lookback=21, smooth=3).loc[t_prev]
    pd.testing.assert_series_equal(before, after)


def test_momentum_score_matches_manual_formula():
    prices = _ramp(n=120)
    lookback, smooth = 21, 3
    score = rotation.momentum_score(prices, lookback=lookback, smooth=smooth)
    t = 80
    recent = prices.iloc[t - smooth + 1: t + 1]["A0"].mean()
    base = prices.iloc[t - lookback - smooth + 1: t - lookback + 1]["A0"].mean()
    expected = recent / base - 1.0
    assert abs(score.iloc[t]["A0"] - expected) < 1e-12


def test_momentum_score_nan_prefix_length():
    prices = _ramp(n=120)
    lookback, smooth = 21, 3
    score = rotation.momentum_score(prices, lookback=lookback, smooth=smooth)
    # shift(lookback) 再 rolling(smooth) -> 前 lookback+smooth-1 行为 NaN
    assert score.iloc[: lookback + smooth - 1].isna().all().all()
    assert score.iloc[lookback + smooth - 1].notna().all()


# ---- 2. 权重结构 ----

def test_rotation_weights_row_sums_are_zero_or_one():
    prices = _ramp(n=120)
    for top_k in (1, 2, 3):
        w = rotation.rotation_weights(prices, top_k=top_k, threshold=0.0)
        sums = w.sum(axis=1).round(10).unique()
        assert set(sums.tolist()) <= {0.0, 1.0}
        # 持仓行恰好 top_k 个标的，且等权
        invested = w[w.sum(axis=1) > 0]
        assert (invested > 0).sum(axis=1).eq(top_k).all()
        positive_vals = invested.values[invested.values > 0]
        assert np.allclose(positive_vals, 1.0 / top_k)


def test_rotation_weights_cash_when_all_momentum_negative():
    prices = _falling(n=120)
    w = rotation.rotation_weights(prices, top_k=1, threshold=0.0)
    # 单调下跌 -> 所有动量 < 0 -> 绝对动量过滤后应全程空仓
    valid = w.iloc[25:]
    assert (valid.sum(axis=1) == 0).all()


def test_rotation_weights_picks_strongest():
    prices = _ramp(n=120)
    # A3 斜率最大（+0.001*3 起始差 + 相同 step，实际涨幅百分比 A0 最大）
    # 用一个人造面板：给 A1 明显更高的涨幅
    px = prices.copy()
    px["A1"] = px["A1"] * (1 + 0.02 * np.arange(len(px)) / len(px))
    w = rotation.rotation_weights(px, top_k=1, threshold=0.0)
    picks = w[w.sum(axis=1) > 0].idxmax(axis=1)
    assert (picks == "A1").mean() > 0.5


# ---- 3. 回测口径 ----

def test_rotation_backtest_nav_starts_at_one():
    prices = _ramp(n=120)
    r = rotation.rotation_backtest(prices, top_k=2, cost=0.0005)
    assert abs(r["nav"].iloc[0] - 1.0) < 1e-12
    assert len(r["nav"]) == len(prices)


def test_rotation_backtest_turnover_and_switches_positive():
    prices = rotation.gen_multi_prices(n=300, n_assets=6, seed=3)
    r = rotation.rotation_backtest(prices, top_k=2, cost=0.0005)
    assert r["total_turnover"] > 0
    assert r["num_switches"] > 0
    assert set(r["metrics"]) >= {"total_return", "sharpe", "max_drawdown"}


def test_rotation_requires_at_least_two_assets():
    prices = _ramp(n=60, k=1)
    with pytest.raises(ValueError):
        rotation.rotation_backtest(prices)


def test_buy_and_hold_matches_equal_weight():
    prices = rotation.gen_multi_prices(n=200, n_assets=5, seed=5)
    nav = rotation.buy_and_hold(prices)
    ret = prices.pct_change().fillna(0.0)
    expected = (1 + ret.mean(axis=1)).cumprod()
    assert np.allclose(nav.values, expected.values)


# ---- 4. 生成器可复现 ----

def test_gen_multi_prices_reproducible():
    a = rotation.gen_multi_prices(n=200, n_assets=6, seed=42)
    b = rotation.gen_multi_prices(n=200, n_assets=6, seed=42)
    pd.testing.assert_frame_equal(a, b)
    c = rotation.gen_multi_prices(n=200, n_assets=6, seed=43)
    assert not np.allclose(a.values, c.values)


# ---- 5. 定性结论：有趋势则轮动有效，无趋势则失效 ----

def test_rotation_beats_buy_and_hold_when_trend_exists():
    prices = rotation.gen_multi_prices(n=750, n_assets=8, seed=7, trend_amp=0.0015)
    rot = rotation.rotation_backtest(prices, top_k=3, cost=0.0005)
    bh = rotation.compute_nav_metrics(rotation.buy_and_hold(prices))
    assert rot["metrics"]["total_return"] > bh["total_return"]
    assert rot["metrics"]["sharpe"] > bh["sharpe"]


def test_rotation_underperforms_without_trend():
    """无趋势随机游走：动量无信号可捕捉，轮动只贡献成本 -> 跑输买入持有。"""
    prices = rotation.gen_multi_prices(n=750, n_assets=8, seed=7, trend_amp=0.0)
    rot = rotation.rotation_backtest(prices, top_k=1, cost=0.0005)
    bh = rotation.compute_nav_metrics(rotation.buy_and_hold(prices))
    assert rot["metrics"]["total_return"] < bh["total_return"]
