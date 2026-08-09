"""A2 换手率控制单测：稳定性保留、新进入数量受限、关闭时不动。"""
import pandas as pd

from scripts.daily_scan import apply_turnover


def test_keeps_stable_prev():
    cfg = {"turnover": {"enabled": True, "max_turnover_pct": 0.5, "min_score_gap": 0.2}}
    new = pd.DataFrame({"code": ["A", "B", "C"], "score": [0.9, 0.8, 0.1],
                        "position_pct": [0.1, 0.1, 0.1], "rank": [1, 2, 3]})
    prev = pd.DataFrame({"code": ["A", "B"], "score": [0.85, 0.82]})
    out = apply_turnover(new, prev, cfg, 3)
    # A,B 分数未明显下滑保留；C 新进入，allow=round(0.5*2)=1，room=1 -> 保留C
    assert set(out["code"]) == {"A", "B", "C"}


def test_caps_new_entries():
    cfg = {"turnover": {"enabled": True, "max_turnover_pct": 0.0, "min_score_gap": 0.2}}
    new = pd.DataFrame({"code": ["A", "B", "C"], "score": [0.9, 0.8, 0.7],
                        "position_pct": [0.1, 0.1, 0.1], "rank": [1, 2, 3]})
    prev = pd.DataFrame({"code": ["A"], "score": [0.85]})
    out = apply_turnover(new, prev, cfg, 3)
    # max_turn=0 不允许任何新进入 -> 仅保留 A
    assert set(out["code"]) == {"A"}


def test_disabled_returns_all_new():
    cfg = {"turnover": {"enabled": False}}
    new = pd.DataFrame({"code": ["A", "B"], "score": [0.9, 0.8],
                        "position_pct": [0.1, 0.1], "rank": [1, 2]})
    prev = pd.DataFrame({"code": ["A"], "score": [0.85]})
    out = apply_turnover(new, prev, cfg, 2)
    assert set(out["code"]) == {"A", "B"}


def test_drops_slipped_prev():
    cfg = {"turnover": {"enabled": True, "max_turnover_pct": 1.0, "min_score_gap": 0.2}}
    new = pd.DataFrame({"code": ["A", "C"], "score": [0.9, 0.7],
                        "position_pct": [0.1, 0.1], "rank": [1, 2]})
    prev = pd.DataFrame({"code": ["A", "B"], "score": [0.85, 0.95]})
    # B 上期0.95，本期不在 new（分数下滑出局）-> 被换出；A 保留；C 新进入
    out = apply_turnover(new, prev, cfg, 2)
    assert "B" not in set(out["code"])
    assert set(out["code"]) == {"A", "C"}
