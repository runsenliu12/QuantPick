"""A3 组合层优化单测：风险平价/目标波动权重。"""
import numpy as np
import pandas as pd

from src.risk import portfolio_weights, regime_scale


def test_risk_parity_low_vol_higher_weight():
    cfg = {"portfolio": {"method": "risk_parity", "max_position_pct": 0.5}}
    vol = pd.Series([10.0, 20.0, 30.0], index=["a", "b", "c"])
    w = portfolio_weights(vol, cfg)
    assert abs(w.sum() - 1.0) < 1e-9
    assert w["a"] > w["b"] > w["c"]
    assert w.max() <= 0.5 + 1e-9


def test_equal_method():
    cfg = {"portfolio": {"method": "equal", "max_position_pct": 0.5}}
    vol = pd.Series([10.0, 20.0, 30.0], index=["a", "b", "c"])
    w = portfolio_weights(vol, cfg)
    assert np.allclose(w.values, [1 / 3, 1 / 3, 1 / 3])


def test_vol_target_scales_by_inv_vol():
    cfg = {"portfolio": {"method": "vol_target", "target_vol": 0.15, "max_position_pct": 1.0}}
    vol = pd.Series([10.0, 20.0], index=["a", "b"])
    w = portfolio_weights(vol, cfg)
    assert abs(w.sum() - 1.0) < 1e-9
    # 目标波动高->低波动标的高权重
    assert w["a"] > w["b"]


def test_cap_sum_equals_one():
    # 封顶后剩余额度按比例补回，保证和=1；标的数*maxp>1 时不会突破封顶
    cfg = {"portfolio": {"method": "risk_parity", "max_position_pct": 0.12}}
    vol = pd.Series(np.linspace(5.0, 30.0, 12), index=[f"s{i}" for i in range(12)])
    w = portfolio_weights(vol, cfg)
    assert abs(w.sum() - 1.0) < 1e-9
    assert w.max() <= 0.12 + 1e-9


def _idx(vals):
    return pd.Series(vals, index=pd.date_range("2020-01-01", periods=len(vals)))


def test_regime_scale_risk_on_when_above_ma():
    cfg = {"regime": {"ma_window": 3, "risk_on_scale": 1.0, "risk_off_scale": 0.3}}
    # 收盘价持续上行，最后一日高于 MA -> risk_on
    close = _idx([10.0, 11.0, 12.0, 13.0, 14.0])
    assert regime_scale(close, cfg) == 1.0


def test_regime_scale_risk_off_when_below_ma():
    cfg = {"regime": {"ma_window": 3, "risk_on_scale": 1.0, "risk_off_scale": 0.3}}
    # 收盘价持续下行，最后一日低于 MA -> risk_off
    close = _idx([14.0, 13.0, 12.0, 11.0, 10.0])
    assert regime_scale(close, cfg) == 0.3


def test_regime_scale_as_of_is_point_in_time():
    cfg = {"regime": {"ma_window": 3, "risk_on_scale": 1.0, "risk_off_scale": 0.3}}
    # 整体先跌后涨：在下跌段 as_of 应为 risk_off，末日整体又 risk_on
    close = _idx([14.0, 13.0, 12.0, 11.0, 10.0, 13.0, 16.0])
    d_off = close.index[4]   # 跌到最低点
    d_on = close.index[-1]   # 反弹后
    assert regime_scale(close, cfg, as_of=d_off) == 0.3
    assert regime_scale(close, cfg, as_of=d_on) == 1.0


def test_regime_scale_fallback_when_insufficient():
    cfg = {"regime": {"ma_window": 200, "risk_on_scale": 1.0, "risk_off_scale": 0.3}}
    close = _idx([10.0, 11.0, 12.0])  # 长度 < ma_window -> 退化为 risk_on
    assert regime_scale(close, cfg) == 1.0
