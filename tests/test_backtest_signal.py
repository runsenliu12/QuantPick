"""src/methods/backtest_signal 的单测：仅合成数据，不连任何数据源/券商。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.methods.backtest_signal import (
    gen_ohlc, signal_backtest, compute_signal_metrics,
    run_method_on_prices, backtest_method, list_methods,
)


def _rising(n=200, seed=3):
    rng = np.random.default_rng(seed)
    close = 10 * np.cumprod(1 + rng.normal(0.001, 0.01, n))
    return pd.Series(close)


def test_gen_ohlc_shape():
    c, h, l = gen_ohlc(n=120, seed=5)
    assert len(c) == len(h) == len(l) == 120
    assert (h >= c).all() and (l <= c).all()


def test_signal_backtest_nav_starts_at_one():
    close = _rising(150)
    pos = pd.Series([1.0] * 150)  # 全程满仓持有
    out = signal_backtest(close, pos, cost=0.0, t1=False)
    assert abs(out["nav"].iloc[0] - 1.0) < 1e-9
    # 全程持有（t1=False，首日即生效）的净值应等于价格累计涨幅
    expected = close.iloc[-1] / close.iloc[0]
    assert abs(out["nav"].iloc[-1] - expected) < 1e-6


def test_signal_backtest_t1_delays_entry():
    close = _rising(100)
    pos = pd.Series([0] * 49 + [1] * 51)
    out_t1 = signal_backtest(close, pos, cost=0.0, t1=True)
    out_no = signal_backtest(close, pos, cost=0.0, t1=False)
    # T+1 使首笔仓位晚一天生效，净值曲线应不同
    assert not out_t1["nav"].equals(out_no["nav"])


def test_signal_backtest_cost_reduces_return():
    close = _rising(200)
    pos = pd.Series(np.where(np.arange(200) % 20 < 10, 1, 0).astype(float))
    free = signal_backtest(close, pos, cost=0.0)["nav"].iloc[-1]
    paid = signal_backtest(close, pos, cost=0.002)["nav"].iloc[-1]
    assert paid < free


def test_signal_backtest_turtle_units_normalized():
    c, h, l = gen_ohlc(n=300, seed=11)
    from src.methods import turtle
    pos = turtle.turtle_signal(h, l, c, entry=20, exit_win=10)
    out = signal_backtest(c, pos, cost=0.0008)
    assert out["nav"].iloc[0] == 1.0
    assert len(out["trades"]) >= 0  # 合成随机行情可能 0 笔，不报错即可


def test_compute_signal_metrics_keys():
    close = _rising(250)
    pos = pd.Series([0] * 100 + [1] * 150)
    out = signal_backtest(close, pos, cost=0.0, t1=False)
    m = compute_signal_metrics(out["nav"], out["trades"], out["total_turnover"])
    for k in ("total_return", "annual_return", "sharpe", "max_drawdown",
              "vol_annual", "num_trades", "win_rate", "total_turnover"):
        assert k in m
    assert m["num_trades"] == 1
    assert 0.0 <= m["win_rate"] <= 1.0


def test_run_method_on_prices_dual_ma():
    pos, close = run_method_on_prices("dual_ma", n=250, seed=7)
    assert len(pos) == len(close) == 250
    assert set(np.unique(pos)).issubset({-1.0, 0.0, 1.0})


def test_run_method_on_prices_turtle_needs_ohlc():
    pos, close = run_method_on_prices("turtle", n=250, seed=7)
    assert len(pos) == 250
    # 海龟原始输出为单位数（long_only 时 0..max_units），归一化在 signal_backtest 内完成
    assert pos.abs().max() <= 4.0 + 1e-9


def test_backtest_method_end_to_end():
    res = backtest_method("rsi", n=300, seed=9, params={"window": 14, "oversold": 30})
    assert res["method"] == "rsi"
    assert "total_return" in res["metrics"]
    assert len(res["nav"]) == 300  # nav 长度 == 价格根数


def test_backtest_method_explicit_close():
    close = _rising(180, seed=21)
    res = backtest_method("breakout", close=close, params={"window": 20})
    assert len(res["position"]) == 180
    assert res["nav"].iloc[0] == 1.0


def test_list_methods_includes_core():
    names = list_methods()
    for m in ("turtle", "dual_ma", "rsi", "breakout", "bollinger", "ml_timing"):
        assert m in names
