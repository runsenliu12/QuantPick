"""ML 打分（walk-forward，防未来函数）测试：纯 numpy/pandas，无第三方依赖。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src import ml


def test_walk_forward_shape_and_warmup():
    n_d, n_c, n_f = 80, 5, 3
    rng = np.random.default_rng(0)
    X = rng.normal(0, 1, (n_d, n_c, n_f))
    y = rng.normal(0, 1, (n_d, n_c))
    sc = ml.walk_forward_panel(X, y, warmup=60)
    assert sc.shape == (n_d, n_c)
    assert np.isnan(sc[:60]).all()
    assert np.isfinite(sc[60:]).all()


def test_make_labels_tail_nan():
    n = 30
    r = pd.DataFrame(np.ones((n, 2)) * 0.01)
    lab = ml.make_labels(r, horizon=5)
    assert lab.iloc[-5:].isna().all().all()


def test_no_future_leakage():
    """严格扩张窗口：第 d 日的分数只依赖 d 日之前的数据，改未来数据不应影响。"""
    n_d, n_c, n_f = 80, 5, 3
    rng = np.random.default_rng(1)
    X = rng.normal(0, 1, (n_d, n_c, n_f))
    y = rng.normal(0, 1, (n_d, n_c))
    sc1 = ml.walk_forward_panel(X, y, warmup=60)
    X2 = X.copy()
    X2[70:] = 0.0  # 破坏未来数据
    sc2 = ml.walk_forward_panel(X2, y, warmup=60)
    assert np.allclose(sc1[:70], sc2[:70], equal_nan=True)


def test_ml_score_shape():
    n_d, n_c = 80, 6
    codes = [f"C{i}" for i in range(n_c)]
    dates = pd.date_range("2024-01-01", periods=n_d, freq="D")
    rng = np.random.default_rng(2)
    ret = pd.DataFrame(rng.normal(0, 0.02, (n_d, n_c)), index=dates, columns=codes)
    fps = {"mom": ret * 1.0, "val": ret * -0.5}
    sc = ml.ml_score(fps, ret, horizon=10, warmup=60)
    assert sc.shape == (n_d, n_c)
    assert sc.index.equals(dates) and list(sc.columns) == codes
