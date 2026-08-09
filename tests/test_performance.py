"""performance 模块单测：用合成行情 + 假 fetcher，无需网络即可验证对账逻辑。

运行：pytest tests/test_performance.py
"""
from __future__ import annotations

import os
import sqlite3
import tempfile

import numpy as np
import pandas as pd

from src.performance import (
    compute_performance, max_drawdown, annualized_sharpe,
    total_return, build_html_report,
)

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_prices(n=80, seed=1, trend=0.002):
    rng = np.random.default_rng(seed)
    # 带轻微上行趋势的随机游走，保证大部分持有期为正
    rets = rng.normal(trend, 0.01, n)
    close = 10 * np.cumprod(1 + rets)
    idx = pd.bdate_range("2024-01-02", periods=n)
    return pd.Series(close, index=idx)


def _make_fetcher(prices: dict, bench: pd.Series):
    class Fake:
        def get_stock_hist(self, code):
            return pd.DataFrame({"日期": prices[code].index, "收盘": prices[code].values})
        def get_etf_hist(self, code):
            return pd.DataFrame({"日期": prices[code].index, "收盘": prices[code].values})
        def get_index_hist(self, symbol):
            return pd.DataFrame({"日期": bench.index, "收盘": bench.values})
    return Fake()


def _make_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE selections (
        id INTEGER PRIMARY KEY AUTOINCREMENT, run_date TEXT, kind TEXT, code TEXT,
        name TEXT, rank INTEGER, score REAL, position_pct REAL,
        stop_loss_pct REAL, factors TEXT)""")
    for r in rows:
        conn.execute(
            "INSERT INTO selections (run_date,kind,code,name,rank,score,position_pct,stop_loss_pct,factors) "
            "VALUES (?,?,?,?,?,?,?,?,?)", r)
    conn.commit(); conn.close()


CFG = {"benchmark": "000300", "performance": {"horizons": [5, 20, 60]}}


def test_pure_metrics():
    nav = pd.Series([1.0, 1.05, 0.95, 1.10])
    assert abs(total_return(nav) - 0.10) < 1e-9
    dd = max_drawdown(nav)
    assert dd < 0 and abs(dd - (-0.095238)) < 0.01  # 0.95/1.05 - 1
    daily = pd.Series([0.01, -0.005, 0.02, 0.003])
    assert annualized_sharpe(daily) > 0


def test_empty_db():
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, "q.db")
        _make_db(db, [])
        res = compute_performance(db, CFG, fetcher=_make_fetcher({}, pd.Series([1.0])))
        assert res.get("empty") is True


def test_reconcile_basic():
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, "q.db")
        p = {  # 两个标的，各自一路上行
            "600000": _make_prices(n=80, seed=1, trend=0.003),
            "600001": _make_prices(n=80, seed=2, trend=0.002),
        }
        bench = _make_prices(n=80, seed=9, trend=0.001)
        # 两个推荐日（不同日期），均取首日为 run_date
        d0 = p["600000"].index[0].date().isoformat()
        d1 = p["600000"].index[20].date().isoformat()
        rows = [
            (d0, "stock", "600000", "股票A", 1, 0.9, 0.12, 0.08, "{}"),
            (d0, "etf", "600001", "ETF_B", 2, 0.8, 0.10, 0.06, "{}"),
            (d1, "stock", "600000", "股票A", 1, 0.9, 0.12, 0.08, "{}"),
        ]
        _make_db(db, rows)
        fetcher = _make_fetcher(p, bench)
        res = compute_performance(db, CFG, fetcher=fetcher, horizons=(5, 20, 60))
        assert res.get("empty") is False
        assert res["rec_count"] == 3
        # 上行行情下，5/20/60 日收益应多为正
        for h in ("5", "20", "60"):
            assert h in res["per_horizon"]
            assert res["per_horizon"][h]["win_rate"] >= 50
        # 净值序列与日期对齐
        assert len(res["nav"]["dates"]) == len(res["nav"]["strategy"])
        assert len(res["nav"]["strategy"]) == len(res["nav"]["benchmark"])
        # 报告可生成（非空字符串）
        html = build_html_report(res)
        assert "<html" in html and "战绩" in html


def test_html_empty():
    html = build_html_report({"empty": True, "message": "无数据"})
    assert "无数据" in html
