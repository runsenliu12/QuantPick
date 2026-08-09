"""回测：动量因子的截面 IC / ICIR 与等权持有净值（演示版，默认小样本）。

说明：这是验证因子"是否有效"的最小示例，不是实盘策略。完整回测请扩大 --pool，
并确保数据已缓存（先跑一次 daily_scan 或加大 cache_days）。

用法：
    python scripts/backtest.py --pool 80 --lookback 60 --forward 20 --top 10
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from src.config import load_config, get
from src.data import DataFetcher


def build_panel(fetcher: DataFetcher, codes, min_hist: int = 120) -> pd.DataFrame:
    panel = {}
    for code in codes:
        try:
            hist = fetcher.get_stock_hist(code)
            if hist is None or hist.empty or "收盘" not in hist.columns:
                continue
            close = pd.to_numeric(hist["收盘"], errors="coerce").dropna()
            if len(close) < min_hist:
                continue
            panel[code] = close.pct_change().dropna()
        except Exception:
            continue
    return pd.DataFrame(panel).dropna(how="all")


def compute_ic(panel: pd.DataFrame, lookback: int, forward: int) -> pd.Series:
    factor = panel.rolling(lookback).sum().shift(forward)
    label = panel.rolling(forward).sum()
    ic_series = []
    for date in factor.index:
        f = factor.loc[date]
        l = label.loc[date]
        common = f.dropna().index.intersection(l.dropna().index)
        if len(common) < 10:
            continue
        corr = f[common].corr(l[common])
        if pd.notna(corr):
            ic_series.append(corr)
    return pd.Series(ic_series)


def backtest_naive(panel: pd.DataFrame, lookback: int, hold: int, top_n: int) -> pd.Series:
    score = panel.rolling(lookback).sum().shift(1)
    dates = panel.index[lookback:]
    port_ret = []
    for date in dates:
        s = score.loc[date].dropna().sort_values(ascending=False)
        if len(s) < top_n:
            port_ret.append(0.0)
            continue
        sel = s.head(top_n).index
        port_ret.append(panel.loc[date, sel].mean())
    return (1 + pd.Series(port_ret, index=dates).fillna(0)).cumprod()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", type=int, default=50)
    ap.add_argument("--lookback", type=int, default=60)
    ap.add_argument("--forward", type=int, default=20)
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args()

    cfg = load_config()
    fetcher = DataFetcher(sqlite_path=get(cfg, "data", "sqlite_path", default="data/quantpick.db"))
    try:
        uni = fetcher.get_stock_universe()
        uni = uni.sort_values("amount", ascending=False).head(args.pool)
        codes = uni["code"].astype(str).tolist()
        print(f"[info] 股票池 {len(codes)} 只，拉取历史…")
        panel = build_panel(fetcher, codes)
        print(f"[info] 可用 {panel.shape[1]} 只")
        if panel.shape[1] < args.top:
            print("[warn] 可用标的不够，扩大 --pool 或检查网络后重试")
            return
        ics = compute_ic(panel, args.lookback, args.forward)
        if len(ics):
            print(f"IC均值={ics.mean():.3f}  ICIR={ics.mean()/ics.std():.3f}  "
                  f"胜率={(ics > 0).mean():.2%}")
        nav = backtest_naive(panel, args.lookback, args.forward, args.top)
        total = nav.iloc[-1] - 1
        ann = (1 + total) ** (252 / len(nav)) - 1 if len(nav) else 0
        print(f"样本期收益={total:.2%}  年化≈{ann:.2%}  期末净值={nav.iloc[-1]:.2f}")
    finally:
        fetcher.close()


if __name__ == "__main__":
    main()
