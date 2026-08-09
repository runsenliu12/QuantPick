"""A3 组合层优化单测：风险平价/目标波动权重。"""
import numpy as np
import pandas as pd

from src.risk import portfolio_weights


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
