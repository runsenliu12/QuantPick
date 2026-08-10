"""覆盖率诊断单测：纯函数 + factor_coverage 的阈值告警逻辑（mock 取数，无需联网）。"""
from __future__ import annotations

import pandas as pd
from unittest.mock import patch

from src import coverage as cov


def test_summarize_coverage_counts():
    df = pd.DataFrame({
        "pe": [1.0, 2.0, None],
        "pb": [None, None, None],
        "roe": [5.0, 6.0, 7.0],
    })
    rep = cov.summarize_coverage(df, ["pe", "pb", "roe"])
    assert rep["n"] == 3
    by = {f["factor"]: f for f in rep["factors"]}
    assert by["pe"]["present"] == 2 and by["pe"]["coverage"] == round(2 / 3, 4)
    assert by["pb"]["present"] == 0 and by["pb"]["coverage"] == 0.0
    assert by["roe"]["present"] == 3 and by["roe"]["coverage"] == 1.0


def test_summarize_coverage_missing_column():
    df = pd.DataFrame({"pe": [1.0]})
    rep = cov.summarize_coverage(df, ["pe", "dividend_yield"])
    by = {f["factor"]: f for f in rep["factors"]}
    assert by["dividend_yield"]["coverage"] == 0.0
    assert by["dividend_yield"]["present"] == 0


def _stock_df(pe=None, pb=None, roe=None, dy=None):
    return pd.DataFrame({
        "code": ["600000"], "name": ["X"],
        "ret_20": [1.0], "ret_60": [1.0], "vol_60": [1.0],
        "roe": [roe], "debt_ratio": [1.0],
        "pe": [pe], "pb": [pb], "dividend_yield": [dy],
        "fund_flow_5": [0.0], "fund_flow_20": [0.0],
    })


def _etf_df(exp=None, te=None):
    return pd.DataFrame({
        "code": ["510300"], "name": ["Y"],
        "ret_20": [1.0], "ret_60": [1.0], "vol_60": [1.0],
        "aum": [1e10], "amount": [1e8],
        "premium": [0.0], "expense_ratio": [exp], "tracking_error": [te],
    })


def test_factor_coverage_flags_low_critical():
    def fake_rows(fetcher, cfg, kind):
        return _stock_df(pe=None, pb=None, roe=None, dy=None) if kind == "stock" \
            else _etf_df(exp=None, te=None)
    with patch.object(cov.selection, "compute_factor_rows", side_effect=fake_rows):
        rep = cov.factor_coverage(None, {})
    assert rep["stock"]["n"] == 1
    assert any("pe" in fl for fl in rep["flags"])
    assert any("pb" in fl for fl in rep["flags"])
    assert any("expense_ratio" in fl for fl in rep["flags"])
    assert any("tracking_error" in fl for fl in rep["flags"])


def test_factor_coverage_no_flags_when_healthy():
    def fake_rows(fetcher, cfg, kind):
        return _stock_df(pe=10.0, pb=1.0, roe=5.0, dy=2.0) if kind == "stock" \
            else _etf_df(exp=0.5, te=1.0)
    with patch.object(cov.selection, "compute_factor_rows", side_effect=fake_rows):
        rep = cov.factor_coverage(None, {})
    assert rep["flags"] == []
