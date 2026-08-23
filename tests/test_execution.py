"""执行层测试：目标组合生成、代码归一、三平台生成器、纸面模拟器。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.execution import build_target, save_target, load_target, simulate, fetch_prices_demo
from src.execution import ptrade_adapter, qmt_adapter, joinquant_adapter
from src.execution.common import norm_code

DEMO_CANDS = {
    "stocks": [
        {"code": "600000.SH", "name": "浦发银行", "position_pct": 0.10, "stop_loss_pct": 0.10, "rank": 1, "score": 1.2},
        {"code": "000001.SZ", "name": "平安银行", "position_pct": 0.10, "stop_loss_pct": 0.10, "rank": 2, "score": 1.0},
    ],
    "etfs": [
        {"code": "510300.SH", "name": "沪深300ETF", "position_pct": 0.20, "stop_loss_pct": 0.08, "rank": 1, "score": 1.5},
    ],
    "regime": {"state": "risk_on", "scale": 0.8},
}


def test_build_target_normalizes_to_scale():
    t = build_target(DEMO_CANDS)
    wsum = sum(v["weight"] for v in t["positions"].values())
    assert abs(wsum - 0.8) < 1e-6, wsum
    assert t["scale"] == 0.8
    assert "600000.SH" in t["positions"]
    assert t["positions"]["600000.SH"]["stop_loss"] == 0.10


def test_save_load_roundtrip(tmp_path):
    t = build_target(DEMO_CANDS)
    p = tmp_path / "target.json"
    save_target(t, str(p))
    t2 = load_target(str(p))
    assert t2["positions"] == t["positions"]


def test_norm_code():
    assert norm_code("600000.SH", "ptrade") == "600000.SH"
    assert norm_code("600000.SH", "qmt") == "600000"
    assert norm_code("600000.SH", "joinquant") == "600000.XSHG"
    assert norm_code("000001.SZ", "joinquant") == "000001.XSHE"


def test_ptrade_generate_contains_target_and_markers():
    t = build_target(DEMO_CANDS)
    code = ptrade_adapter.generate(t)
    assert "TARGET = {" in code
    assert "order_target_value" in code
    assert "initialize(context)" in code
    assert "600000.SH" in code  # ptrade 保持后缀


def test_qmt_generate_strips_code():
    t = build_target(DEMO_CANDS)
    code = qmt_adapter.generate(t)
    assert "xtquant" in code
    assert "order_stock" in code
    assert "600000" in code and "600000.SH" not in code  # QMT 用纯数字


def test_joinquant_generate_xshg():
    t = build_target(DEMO_CANDS)
    code = joinquant_adapter.generate(t)
    assert "600000.XSHG" in code  # 聚宽格式
    assert "order_target_value" in code


def test_simulate_runs_on_demo_prices():
    t = build_target(DEMO_CANDS)
    prices = fetch_prices_demo(t, n_days=60, seed=1)
    r = simulate(t, prices)
    assert len(r["nav"]) == 60
    assert isinstance(r["final_value"], float)
    assert r["max_drawdown"] >= 0


def test_simulate_no_prices_is_safe():
    t = build_target(DEMO_CANDS)
    r = simulate(t, {})
    assert r["error"] == "no price data"
    assert r["nav"] == []
