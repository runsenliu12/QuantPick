"""因子有效性（IC / ICIR）测试：纯 numpy/pandas，无第三方依赖。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src import ic


def test_demo_ic_shapes():
    fps, fwd = ic.demo_ic()
    assert set(fps.keys()) == {"effective", "noise"}
    rep = ic.report(fps, fwd)
    assert "effective" in rep and "noise" in rep


def test_effective_factor_has_positive_ic():
    fps, fwd = ic.demo_ic()
    rep = ic.report(fps, fwd)
    # effective 因子与后向收益人为正相关 -> IC 显著为正
    assert rep["effective"]["ic"] > 0.1
    # noise 因子无关 -> |IC| 应明显小于 effective
    assert abs(rep["noise"]["ic"]) < rep["effective"]["ic"]


def test_make_fwd_returns_shift():
    r = pd.DataFrame(np.arange(10.0).reshape(10, 1))
    f = ic.make_fwd_returns(r, horizon=2)
    assert np.isnan(f.iloc[-2, 0])  # 末尾 horizon 期为 NaN（无未来数据）
    assert f.iloc[0, 0] == 2.0


def test_summarize_empty():
    s = ic.summarize(pd.Series([np.nan, np.nan]))
    assert s["n"] == 0
    assert s["ic"] is None
