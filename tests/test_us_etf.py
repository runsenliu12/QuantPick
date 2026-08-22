"""美股 ETF 脚手架测试：demo 路径无需 yfinance / 网络。"""
from __future__ import annotations

import pandas as pd

from src import us_etf as ue


def _cfg(enabled=False):
    return {
        "us_etf": {
            "enabled": enabled,
            "symbols": ["SPY", "QQQ", "IWM", "VTI", "GLD"],
            "top_n": 3,
            "weights": {"momentum": 0.35, "liquidity": 0.20, "scale": 0.15,
                        "premium": 0.10, "expense": 0.20},
        },
        "portfolio": {"max_position_pct": 0.12},
        "risk": {"min_stop_loss_pct": 0.05, "max_stop_loss_pct": 0.15,
                 "stop_vol_multiplier": 0.5},
    }


def test_demo_returns_dataframe():
    df = ue.rank_us_etfs(_cfg(), demo=True)
    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert len(df) == 3


def test_demo_schema_matches_history():
    df = ue.rank_us_etfs(_cfg(), demo=True)
    for col in ("code", "name", "rank", "score", "position_pct", "stop_loss_pct"):
        assert col in df.columns
    # 权重应在 (0, max_position_pct] 区间
    assert (df["position_pct"] > 0).all()
    assert (df["position_pct"] <= 0.12 + 1e-9).all()


def test_disabled_returns_none():
    assert ue.rank_us_etfs(_cfg(enabled=False), demo=False) is None


def test_build_us_report():
    df = ue.rank_us_etfs(_cfg(), demo=True)
    rep = ue.build_us_report(df)
    assert "美股 ETF" in rep
    assert "SPY" in rep or "QQQ" in rep
