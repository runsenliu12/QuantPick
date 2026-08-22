from __future__ import annotations

from src import server as s


def test_quote_demo_shape():
    d = s.get_quote("600000", kind="stock", n=120, demo=True)
    assert d["source"] == "demo"
    assert d["code"] == "600000"
    assert d["kind"] == "stock"
    rows = d["rows"]
    assert len(rows) == 120
    # 每根 K 线字段齐全
    for r in rows:
        assert set(r) == {"date", "open", "high", "low", "close", "volume"}
        assert r["high"] >= max(r["open"], r["close"])
        assert r["low"] <= min(r["open"], r["close"])
        assert r["volume"] >= 0


def test_quote_deterministic_by_code():
    a = s.get_quote("600000", demo=True)
    b = s.get_quote("600000", demo=True)
    # 同一 code 合成数据应一致（用 code 作随机种子）
    assert [r["close"] for r in a["rows"]] == [r["close"] for r in b["rows"]]


def test_quote_etf_demo():
    d = s.get_quote("510300", kind="etf", n=60, demo=True)
    assert d["kind"] == "etf"
    assert len(d["rows"]) == 60


def test_quote_real_returns_list_or_demo():
    # 真实接口在无 AKShare / 无历史时会回退 demo，而不抛异常
    d = s.get_quote("600519", kind="stock", n=120, demo=False)
    assert "rows" in d and "source" in d
    assert d["source"] in ("real", "demo")
    assert isinstance(d["rows"], list)
