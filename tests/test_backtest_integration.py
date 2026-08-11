"""回测端到端集成测试：用 FakeFetcher 验证逐日持有与 regime 缩放真实生效。

避免两类回归：
1. 回测只在调仓日步进（ret_matrix 被截到调仓日），导致"日度持有/涨停跌停约束"形同虚设。
2. regime 缩放未接入，回测永远满仓、与实盘口径不一致。
"""
import numpy as np
import pandas as pd

import scripts.backtest as bt


DATES = pd.date_range("2024-01-01", periods=200, freq="D")
CODES = [f"C{i:03d}" for i in range(8)]


def _make_close(seed):
    r = np.random.default_rng(seed).normal(0.0005, 0.02, len(DATES))
    return pd.Series(10 * np.cumprod(1 + r), index=DATES)


class FakeFetcher:
    def get_stock_universe(self):
        return pd.DataFrame(
            {"code": CODES, "name": CODES, "market_cap": [1e10] * 8, "amount": [1e9] * 8}
        )

    def get_stock_hist(self, code):
        i = int(code[1:])
        df = pd.DataFrame({"收盘": _make_close(i)})
        df["涨跌幅"] = df["收盘"].pct_change().fillna(0.0) * 100
        return df

    def get_index_hist(self, sym):
        # 先涨后跌：前期 risk_on，末段跌破 MA -> risk_off（熊市留现金）
        idx = np.concatenate([np.linspace(3000, 3300, 140), np.linspace(3300, 2900, 60)])
        return pd.DataFrame({"收盘": pd.Series(idx, index=DATES)})

    def get_stock_financials(self, code):
        return {"roe": 0.12, "debt_ratio": 0.5, "pe": 15.0, "pb": 1.5, "dividend_yield": 0.02}

    def close(self):
        pass


def _cfg(regime_enabled: bool) -> dict:
    return {
        "portfolio": {"method": "risk_parity", "max_position_pct": 0.12},
        "turnover": {"max_turnover_pct": 1.0},
        "regime": {
            "enabled": regime_enabled,
            "index": "000300",
            "ma_window": 20,
            "risk_on_scale": 1.0,
            "risk_off_scale": 0.3,
        },
        "data": {"sqlite_path": "x"},
    }


def test_run_backtest_steps_daily():
    """净值序列长度应≈交易日数（逐日持有），而非仅等于调仓期数量。"""
    ff = FakeFetcher()
    res = bt.run_backtest(ff, _cfg(True), pool=8, lookback=60, hold=20,
                          top_n=5, rebalance=21, cost=0.001)
    # 调仓期只有 ~6 个；若只在调仓日步进，nav 长度会≈7。逐日持有应远多于 50。
    assert len(res["nav"]) > 50
    # 首个元素为 1.0 减首日建仓交易成本，应非常接近 1（远小于任何真实波动）
    assert abs(res["nav"].iloc[0] - 1.0) < 0.01


def test_run_backtest_regime_changes_result():
    """regime 开启（熊市留现金）应与关闭（永远满仓）产生不同的回测结果。"""
    ff = FakeFetcher()
    on = bt.run_backtest(ff, _cfg(True), pool=8, lookback=60, hold=20,
                         top_n=5, rebalance=21, cost=0.001)
    off = bt.run_backtest(ff, _cfg(False), pool=8, lookback=60, hold=20,
                          top_n=5, rebalance=21, cost=0.001)
    # 至少总收益不同（熊市留现金会改变暴露）
    assert abs(on["metrics"]["total_return"] - off["metrics"]["total_return"]) > 1e-4
