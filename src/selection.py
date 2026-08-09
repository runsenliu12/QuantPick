"""综合打分与排名：因子 Z-Score 标准化后按权重加权，输出股 / ETF 候选清单。"""
from __future__ import annotations

import pandas as pd
from src.config import get
from src.data import DataFetcher
from src import factors


def zscore(series) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    std = s.std()
    if std == 0 or pd.isna(std):
        return pd.Series(0.0, index=s.index)
    return ((s - s.mean()) / std).fillna(0.0)


def rank_stocks(fetcher: DataFetcher, cfg: dict) -> pd.DataFrame:
    uni = fetcher.get_stock_universe()
    min_cap = get(cfg, "selection", "stock", "min_market_cap", default=5e9)
    min_amt = get(cfg, "selection", "stock", "min_amount", default=5e7)
    scan = get(cfg, "selection", "stock", "scan_count", default=200)
    top_n = get(cfg, "selection", "stock", "top_n", default=10)

    uni = uni[
        (pd.to_numeric(uni["market_cap"], errors="coerce") >= min_cap)
        & (pd.to_numeric(uni["amount"], errors="coerce") >= min_amt)
    ]
    uni = uni.sort_values("amount", ascending=False).head(scan)

    rows = []
    for code in uni["code"].astype(str):
        try:
            rows.append(factors.compute_stock_factors(fetcher, code))
        except Exception:
            continue
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    w = get(cfg, "models", "stock_weights",
            default={"momentum": 0.30, "quality": 0.25, "value": 0.25, "fund_flow": 0.20})

    comp = {
        "momentum": 0.5 * zscore(df["ret_20"]) + 0.5 * zscore(df["ret_60"]),
        "quality": zscore(df["roe"]) - zscore(df["debt_ratio"]),
        "value": -zscore(df["price_to_high"]),
        "fund_flow": 0.5 * zscore(df["fund_flow_5"]) + 0.5 * zscore(df["fund_flow_20"]),
    }
    df["score"] = sum(w.get(k, 0) * comp[k] for k in comp)
    df = df.sort_values("score", ascending=False).head(top_n).reset_index(drop=True)
    df["rank"] = df.index + 1
    return df


def rank_etfs(fetcher: DataFetcher, cfg: dict) -> pd.DataFrame:
    uni = fetcher.get_etf_universe()
    min_amt = get(cfg, "selection", "etf", "min_amount", default=5e7)
    min_aum = get(cfg, "selection", "etf", "min_aum", default=5e8)
    top_n = get(cfg, "selection", "etf", "top_n", default=10)

    uni = uni[pd.to_numeric(uni["amount"], errors="coerce") >= min_amt]

    rows = []
    for _, row in uni.iterrows():
        code = str(row["code"])
        try:
            rows.append(factors.compute_etf_factors(fetcher, code, row.to_dict()))
        except Exception:
            continue
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    if "aum" in df:
        df = df[pd.to_numeric(df["aum"], errors="coerce") >= min_aum]

    w = get(cfg, "models", "etf_weights",
            default={"scale": 0.15, "liquidity": 0.20, "premium": 0.15,
                     "momentum": 0.30, "tracking_error": 0.20})
    comp = {
        "scale": zscore(df["aum"]),
        "liquidity": zscore(df["amount"]),
        "premium": zscore(df["premium"]) if df["premium"].notna().any()
        else pd.Series(0.0, index=df.index),
        "momentum": 0.5 * zscore(df["ret_20"]) + 0.5 * zscore(df["ret_60"]),
        "tracking_error": -zscore(df["vol_60"]),
    }
    df["score"] = sum(w.get(k, 0) * comp[k] for k in comp)
    df = df.sort_values("score", ascending=False).head(top_n).reset_index(drop=True)
    df["rank"] = df.index + 1
    return df


def run_selection(cfg: dict) -> dict:
    fetcher = DataFetcher(
        sqlite_path=get(cfg, "data", "sqlite_path", default="data/quantpick.db"),
        cache_days=get(cfg, "data", "cache_days", default=1),
    )
    try:
        stocks = rank_stocks(fetcher, cfg)
        etfs = rank_etfs(fetcher, cfg)
    finally:
        fetcher.close()
    return {"stocks": stocks, "etfs": etfs}
