from __future__ import annotations

import scripts.backtest as bt


def test_to_api_result_shape():
    res = bt.demo_backtest(pool=12, lookback=60, hold=20, top_n=5, rebalance=21)
    api = bt.to_api_result(res)
    assert set(api.keys()) >= {"nav", "bench_nav", "metrics", "segments", "bench_total_return"}
    # 净值为 [i, value] 列表，且长度合理（逐日持有，远多于调仓次数）
    assert api["nav"] and len(api["nav"]) > 50
    assert api["nav"][0]["i"] == 0 and "value" in api["nav"][0]
    # 策略与基准净值点数一致
    assert api["bench_nav"] and len(api["bench_nav"]) == len(api["nav"])
    # 指标与样本内/外分段齐全
    assert "total_return" in api["metrics"] and "sharpe" in api["metrics"]
    assert "in_sample" in api["segments"] and "out_sample" in api["segments"]


def test_demo_fetcher_runs():
    # 合成数据应能离线跑通完整回测（无需 AKShare / 网络）
    res = bt.demo_backtest(pool=12, lookback=60, hold=20, top_n=5, rebalance=21)
    assert len(res["nav"]) > 50
    assert res["bench_nav"] is not None
    m = res["metrics"]
    assert "total_return" in m and "sharpe" in m and "max_drawdown" in m
