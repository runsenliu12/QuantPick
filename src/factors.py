"""因子计算：选股与选 ETF 的多因子原始数值。

所有函数输出原始数值（不做标准化），标准化与加权在 selection 层完成。
因子计算失败（缺数据）时返回 None，由 selection 层统一按中值处理。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _col(df: pd.DataFrame, *keywords) -> str | None:
    for c in df.columns:
        if any(k in str(c) for k in keywords):
            return c
    return None


def _safe_ratio(a, b):
    try:
        if a is None or b in (None, 0):
            return None
        return float(a) / float(b)
    except Exception:
        return None


def _recent_return(hist: pd.DataFrame, days: int):
    if hist is None or hist.empty or "收盘" not in hist.columns:
        return None
    close = pd.to_numeric(hist["收盘"], errors="coerce").dropna()
    if len(close) <= days:
        return None
    return float((close.iloc[-1] / close.iloc[-1 - days] - 1) * 100)


def _annual_vol(hist: pd.DataFrame, window: int = 60):
    if hist is None or hist.empty or "收盘" not in hist.columns:
        return None
    close = pd.to_numeric(hist["收盘"], errors="coerce").dropna()
    if len(close) < 10:
        return None
    rets = np.log(close.iloc[-window:] / close.iloc[-window:].shift(1)).dropna()
    if len(rets) < 5:
        return None
    return float(rets.std() * np.sqrt(252) * 100)


def _net_inflow_pct(df: pd.DataFrame, n: int):
    if df is None or df.empty:
        return None
    c = _col(df, "主力净流入", "净占比")
    if not c:
        return None
    s = pd.to_numeric(df[c], errors="coerce").dropna().tail(n)
    if s.empty:
        return None
    return float(s.mean())


def compute_stock_factors(fetcher, code: str) -> dict:
    """计算单只股票因子：动量 / 质量 / 估值代理 / 资金流。"""
    f = {"code": code}
    hist = fetcher.get_stock_hist(code)
    f["ret_20"] = _recent_return(hist, 20)
    f["ret_60"] = _recent_return(hist, 60)
    f["vol_60"] = _annual_vol(hist, 60)

    fin = fetcher.get_stock_financials(code)
    f["roe"] = fin.get("roe")
    f["debt_ratio"] = fin.get("debt_ratio")

    if hist is not None and not hist.empty:
        close = pd.to_numeric(hist["收盘"], errors="coerce").dropna()
        if len(close):
            hi = close.tail(252).max()
            f["price_to_high"] = _safe_ratio(float(close.iloc[-1]), hi)
    else:
        f["price_to_high"] = None

    ff = fetcher.get_stock_fund_flow(code)
    f["fund_flow_5"] = _net_inflow_pct(ff, 5)
    f["fund_flow_20"] = _net_inflow_pct(ff, 20)
    return f


def compute_etf_factors(fetcher, code: str, spot_row: dict | None = None) -> dict:
    """计算单只 ETF 因子：规模 / 流动性 / 动量 / 跟踪误差。折溢价需净值，留空。"""
    f = {"code": code}
    hist = fetcher.get_etf_hist(code)
    f["ret_20"] = _recent_return(hist, 20)
    f["ret_60"] = _recent_return(hist, 60)
    f["vol_60"] = _annual_vol(hist, 60)

    if spot_row:
        price = spot_row.get("price")
        shares = spot_row.get("float_shares")
        f["shares"] = shares
        f["amount"] = spot_row.get("amount")
        f["aum"] = (
            float(shares) * float(price)
            if _is_num(shares) and _is_num(price) else None
        )
    else:
        f["aum"] = f["amount"] = f["shares"] = None
    f["premium"] = None  # 折溢价需 IOPV/净值，留待后续接入
    return f


def _is_num(v) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False
