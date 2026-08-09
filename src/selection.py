"""综合打分与排名：因子 Z-Score 标准化（支持行业内中性化）后按权重加权，
输出股 / ETF 候选清单，并附带每个因子的贡献（attribution）用于解释。

核心改进：
- 估值因子从"离高点距离"换成真实 PE/PB/股息率，且 momentum 与 value 不再同源重复。
- 质量因子缺失(财务取不到)时按中性 0 处理，避免静默失效。
- 支持行业内中性化，把"行业 β"和"选股 α"分开。
- 输出因子贡献分解，UI / 推送可展示"为什么选它"。
"""
from __future__ import annotations

import numpy as np
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


def group_zscore(series, groups, min_group: int = 5) -> pd.Series:
    """行业内中性化：在每个 group 内做 z-score；样本不足时退化为全市场 z-score。"""
    s = pd.to_numeric(series, errors="coerce")
    g = pd.Series(list(groups), index=s.index).astype(str)
    out = pd.Series(0.0, index=s.index)
    for name, idx in g.groupby(g).groups.items():
        sub = s.loc[idx]
        if sub.notna().sum() >= min_group:
            std = sub.std()
            out.loc[idx] = ((sub - sub.mean()) / std).fillna(0.0) if std and not pd.isna(std) else 0.0
        else:
            std = s.std()
            out.loc[idx] = ((s - s.mean()) / std).fillna(0.0) if std and not pd.isna(std) else 0.0
    return out


def _neutralize(comp: pd.Series, df: pd.DataFrame, cfg: dict, kind: str) -> pd.Series:
    if (kind == "stock" and get(cfg, "selection", "industry_neutral", default=True)
            and "industry" in df.columns and df["industry"].notna().any()):
        return group_zscore(comp, df["industry"])
    return comp


def score_universe(df: pd.DataFrame, cfg: dict, kind: str) -> pd.DataFrame:
    """纯函数：对含因子列与 industry 的 DataFrame 计算综合得分与因子贡献。

    返回原 df 增加：score、以及每个因子的贡献列 c_<factor>。
    """
    df = df.copy()
    if df.empty:
        return df

    if kind == "stock":
        w = get(cfg, "models", "stock_weights",
                default={"momentum": 0.30, "quality": 0.25, "value": 0.25, "fund_flow": 0.20})
        # 动量
        mom = 0.5 * zscore(df["ret_20"]) + 0.5 * zscore(df["ret_60"])
        # 质量
        q = zscore(df["roe"].fillna(df["roe"].mean())) - zscore(df["debt_ratio"].fillna(df["debt_ratio"].mean()))
        # 估值（真实 PE/PB 低好，股息率高好；缺失按中性 0）
        pe_z = zscore(df["pe"].where(df["pe"] > 0))
        pb_z = zscore(df["pb"].where(df["pb"] > 0))
        div_z = zscore(df["dividend_yield"])
        val = pd.Series(0.0, index=df.index)
        for zc in (pe_z, pb_z, div_z):
            val = val + zc.fillna(0.0)
        val = -val  # 低估值=高分
        # 资金流
        ff = 0.5 * zscore(df["fund_flow_5"].fillna(0)) + 0.5 * zscore(df["fund_flow_20"].fillna(0))
        # 中性化
        mom = _neutralize(mom, df, cfg, kind)
        q = _neutralize(q, df, cfg, kind)
        val = _neutralize(val, df, cfg, kind)
        ff = _neutralize(ff, df, cfg, kind)
        comps = {"momentum": mom, "quality": q, "value": val, "fund_flow": ff}
    else:
        w = get(cfg, "models", "etf_weights",
                default={"scale": 0.15, "liquidity": 0.20, "premium": 0.15,
                         "momentum": 0.30, "tracking_error": 0.20})
        scale = zscore(df["aum"].fillna(df["aum"].mean())) if "aum" in df else zscore(df["amount"])
        liq = zscore(df["amount"].fillna(df["amount"].mean()))
        mom = 0.5 * zscore(df["ret_20"]) + 0.5 * zscore(df["ret_60"])
        te = -zscore(df["tracking_error"].fillna(0))
        exp = -zscore(df["expense_ratio"].fillna(0))
        prem = -zscore(df["premium"].fillna(0)).abs()
        comps = {"scale": scale, "liquidity": liq, "premium": prem,
                 "momentum": mom, "tracking_error": te, "expense": exp}

    score = pd.Series(0.0, index=df.index)
    for k, c in comps.items():
        col = f"c_{k}"
        df[col] = (w.get(k, 0) * c.fillna(0.0)).round(4)
        score = score + df[col]
    df["score"] = score.round(4)
    return df


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
    df["name"] = df["code"].map(uni.set_index("code")["name"].to_dict())
    df = score_universe(df, cfg, "stock")
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
    df["name"] = df["code"].map(uni.set_index("code")["name"].to_dict())
    df = score_universe(df, cfg, "etf")
    df = df.sort_values("score", ascending=False).head(top_n).reset_index(drop=True)
    df["rank"] = df.index + 1
    return df


def run_selection(cfg: dict, fetcher: DataFetcher | None = None) -> dict:
    own = fetcher is None
    if own:
        fetcher = DataFetcher(
            sqlite_path=get(cfg, "data", "sqlite_path", default="data/quantpick.db"),
            cache_days=get(cfg, "data", "cache_days", default=1),
        )
    try:
        stocks = rank_stocks(fetcher, cfg)
        etfs = rank_etfs(fetcher, cfg)
    finally:
        if own:
            fetcher.close()
    return {"stocks": stocks, "etfs": etfs}
