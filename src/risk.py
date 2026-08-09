"""风控层：仓位建议、波动率自适应止损、行业上限、相关性去重、市场状态缩放。

核心理念：系统只输出研究信号，不保证盈利。风控决定你能否活到复利生效的那天。
- 单标仓位封顶，避免一把梭
- 止损线随波动率自适应（高波动给更宽止损，避免被正常波动洗出）
- 行业内上限，避免组合过度集中于同一赛道
- 相关性去重，让组合真正分散
- 市场状态（沪深300 vs MA200）决定整体仓位缩放
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


def _vol_stop(vol_series, sl_min: float, sl_max: float, mult: float) -> np.ndarray:
    """止损随年化波动率自适应：stop = clip(vol * mult, sl_min, sl_max)。"""
    v = pd.to_numeric(vol_series, errors="coerce") / 100.0
    v = v.fillna((sl_min + sl_max) / 2.0)
    return (v * mult).clip(sl_min, sl_max).round(4).values


def _cap_by_industry(df: pd.DataFrame, max_per: int) -> pd.DataFrame:
    if "industry" not in df.columns or max_per <= 0 or df.empty:
        return df.reset_index(drop=True)
    df = df.sort_values("score", ascending=False)
    counts, keep = {}, []
    for _, r in df.iterrows():
        ind = r.get("industry") or "NA"
        counts[ind] = counts.get(ind, 0) + 1
        keep.append(counts[ind] <= max_per)
    return df[keep].reset_index(drop=True)


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


def _dedup_df(df: pd.DataFrame, fetcher: DataFetcher, cfg: dict, kind: str) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    max_corr = get(cfg, "risk", "max_correlation", default=0.7)
    cands = list(zip(df["code"].astype(str), df["score"]))
    deduped = deduplicate_by_correlation(fetcher, cands, max_corr)
    keep = {c for c, _ in deduped}
    return df[df["code"].astype(str).isin(keep)].reset_index(drop=True)


def apply_risk(stock_df: pd.DataFrame, etf_df: pd.DataFrame, cfg: dict) -> dict:
    """给候选清单附加 position_pct / stop_loss_pct 列，并施加行业内上限。"""
    rp = get(cfg, "risk", "max_position_pct", default=0.12)
    sl_min = get(cfg, "risk", "min_stop_loss_pct", default=0.05)
    sl_max = get(cfg, "risk", "max_stop_loss_pct", default=0.15)
    sl_mult = get(cfg, "risk", "stop_vol_multiplier", default=0.5)
    max_per = get(cfg, "selection", "stock", "max_per_industry", default=3)
    out = {}
    if stock_df is not None and not stock_df.empty:
        s = _cap_by_industry(stock_df.copy(), max_per)
        s["position_pct"] = recommend_position(s["score"], rp).round(4).values
        s["stop_loss_pct"] = _vol_stop(s["vol_60"], sl_min, sl_max, sl_mult)
        s = s.reset_index(drop=True)
        s["rank"] = s.index + 1
        out["stocks"] = s
    if etf_df is not None and not etf_df.empty:
        e = etf_df.copy()
        e["position_pct"] = recommend_position(e["score"], rp).round(4).values
        e["stop_loss_pct"] = _vol_stop(e["vol_60"], sl_min, sl_max, sl_mult)
        e = e.reset_index(drop=True)
        e["rank"] = e.index + 1
        out["etfs"] = e
    return out


def finalize(res: dict, cfg: dict, fetcher: DataFetcher | None = None) -> dict:
    """统一收口：apply_risk + 相关性去重(股/ETF) + 市场状态缩放。

    供 daily_scan 与 server 共用，保证两端行为一致。
    """
    out = apply_risk(res.get("stocks"), res.get("etfs"), cfg)

    if fetcher is not None and get(cfg, "risk", "dedup", default=True):
        if "stocks" in out and not out["stocks"].empty:
            out["stocks"] = _dedup_df(out["stocks"], fetcher, cfg, "stock")
        if "etfs" in out and not out["etfs"].empty:
            out["etfs"] = _dedup_df(out["etfs"], fetcher, cfg, "etf")
        # 去重后重排 rank
        for k in ("stocks", "etfs"):
            if k in out and not out[k].empty:
                out[k] = out[k].reset_index(drop=True)
                out[k]["rank"] = out[k].index + 1

    scale, state = 1.0, "risk_on"
    if fetcher is not None and get(cfg, "regime", "enabled", default=True):
        rg = fetcher.get_market_regime(
            get(cfg, "regime", "index", default="000300"),
            get(cfg, "regime", "ma_window", default=200),
        )
        scale, state = rg.get("scale", 1.0), rg.get("state", "risk_on")
        for k in ("stocks", "etfs"):
            if k in out and not out[k].empty:
                out[k]["position_pct"] = (out[k]["position_pct"] * scale).round(4)
    out["regime"] = {"state": state, "scale": scale}
    return out
