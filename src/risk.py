"""风控层：仓位建议、止损线、相关性去重。

核心理念：系统只输出研究信号，不保证盈利。风控决定你能否活到复利生效的那天。
- 单标仓位封顶，避免一把梭
- 个股止损线，截断亏损
- 相关性去重，让组合真正分散
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from src.config import get
from src.data import DataFetcher


def recommend_position(score_series, max_pct: float, total: float = 1.0) -> pd.Series:
    """按得分相对高低分配权重，并封顶到 max_pct。"""
    s = pd.to_numeric(score_series, errors="coerce").fillna(0)
    if len(s) == 0 or s.sum() == 0:
        return pd.Series(np.full(len(s), total / len(s)) if len(s) else [], index=s.index)
    w = s - s.min() + 0.1
    w = w / w.sum() * total
    return w.clip(upper=max_pct)


def deduplicate_by_correlation(fetcher: DataFetcher, candidates, max_corr: float = 0.7):
    """按收益相关性去重：保留高分且两两相关性 < max_corr 的子集。

    candidates: list of (code, score)
    返回精简后的 list of (code, score)
    """
    if len(candidates) <= 1:
        return candidates

    rets = {}
    for code, _score in candidates:
        try:
            hist = (fetcher.get_etf_hist(code)
                    if (code.startswith("5") or code.startswith("1"))
                    else fetcher.get_stock_hist(code))
            if hist is not None and not hist.empty and "收盘" in hist.columns:
                r = np.log(pd.to_numeric(hist["收盘"], errors="coerce").dropna()).diff().dropna()
                if len(r) > 20:
                    rets[code] = r
        except Exception:
            continue

    if len(rets) < 2:
        return candidates

    corr = pd.DataFrame(rets).corr().fillna(0)
    selected = []
    for code, score in sorted(candidates, key=lambda x: -x[1]):
        ok = True
        if code in corr.index:
            for c, _ in selected:
                if c in corr.index and abs(corr.loc[c, code]) >= max_corr:
                    ok = False
                    break
        if ok:
            selected.append((code, score))
    return selected


def apply_risk(stock_df: pd.DataFrame, etf_df: pd.DataFrame, cfg: dict) -> dict:
    """给候选清单附加 position_pct / stop_loss_pct 列。"""
    rp = get(cfg, "risk", "max_position_pct", default=0.12)
    sl = get(cfg, "risk", "stop_loss_pct", default=0.08)
    out = {}
    if stock_df is not None and not stock_df.empty:
        s = stock_df.copy()
        s["position_pct"] = recommend_position(s["score"], rp).round(4).values
        s["stop_loss_pct"] = sl
        out["stocks"] = s
    if etf_df is not None and not etf_df.empty:
        e = etf_df.copy()
        e["position_pct"] = recommend_position(e["score"], rp).round(4).values
        e["stop_loss_pct"] = sl
        out["etfs"] = e
    return out
