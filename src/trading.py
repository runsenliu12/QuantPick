"""交易约束（A1）：把 A 股真实交易规则建模进回测与纸上交易，避免"实验室收益"。

覆盖：
- 涨停买不到：建仓日涨停 → 顺延到之后首个可交易日，窗口耗尽则放弃。
- 跌停卖不出：平仓日跌停 → 顺延到之后首个可交易日。
- 停牌：历史行情缺失（无交易日数据）视为停牌，自动顺延到复牌首日。
- 流动性冲击：成交额过低（< min_liquid_amount）追加单边冲击成本。
- T+1：买入后下一交易日才能卖——本系统"买入持有 N>=5 日"天然满足，调用方无需特判。

全部为纯函数，便于单测，且同时被回测(backtest.py)与纸上交易(performance.py)复用。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import get

DEFAULT_LIMIT_UP = 9.5
DEFAULT_LIMIT_DOWN = -9.5
DEFAULT_MAX_DEFER = 5
DEFAULT_MIN_LIQUID_AMT = 5_000_000.0
DEFAULT_LIQUID_SLIP = 0.003


def is_limit_up(pct, thr: float = DEFAULT_LIMIT_UP):
    """接受标量或 Series，返回同形状的布尔（标量返回 Python bool）。"""
    v = pd.to_numeric(pct, errors="coerce")
    if isinstance(v, pd.Series):
        return v.fillna(-999) >= thr
    f = float(v) if pd.notna(v) else -999.0
    return f >= thr


def is_limit_down(pct, thr: float = DEFAULT_LIMIT_DOWN):
    v = pd.to_numeric(pct, errors="coerce")
    if isinstance(v, pd.Series):
        return v.fillna(999) <= thr
    f = float(v) if pd.notna(v) else 999.0
    return f <= thr


def _pct_series(hist: pd.DataFrame) -> pd.Series:
    """从 hist 取得涨跌幅序列（百分比）。优先'涨跌幅'列，否则用收盘反推。"""
    if hist is None:
        return pd.Series(dtype=float)
    if "涨跌幅" in hist.columns:
        return pd.to_numeric(hist["涨跌幅"], errors="coerce")
    if "收盘" in hist.columns:
        c = pd.to_numeric(hist["收盘"], errors="coerce")
        return (c / c.shift(1) - 1) * 100.0
    return pd.Series(dtype=float)


def liquidity_slippage(amount, cfg: dict | None = None) -> float:
    """成交额不足时的额外单边冲击成本（小数）。成交额足够或无数据返回 0。"""
    thr = (get(cfg, "trading", "min_liquid_amount", default=DEFAULT_MIN_LIQUID_AMT)
           if cfg else DEFAULT_MIN_LIQUID_AMT)
    extra = (get(cfg, "trading", "liquidity_slippage", default=DEFAULT_LIQUID_SLIP)
             if cfg else DEFAULT_LIQUID_SLIP)
    a = pd.to_numeric(amount, errors="coerce")
    if pd.isna(a) or a >= thr:
        return 0.0
    return float(extra)


def resolve_entry(hist: pd.DataFrame, ei: int, cfg: dict | None = None):
    """从 ei 起找首个可买入日（非涨停、非停牌）。

    返回 (actual_ei, entry_price)；窗口内都买不到返回 None。
    """
    if hist is None or ei < 0:
        return None
    close = (pd.to_numeric(hist["收盘"], errors="coerce")
             if "收盘" in hist.columns else pd.Series(dtype=float))
    pct = _pct_series(hist)
    up = (get(cfg, "trading", "limit_up_pct", default=DEFAULT_LIMIT_UP)
          if cfg else DEFAULT_LIMIT_UP)
    max_defer = (get(cfg, "trading", "max_defer_days", default=DEFAULT_MAX_DEFER)
                 if cfg else DEFAULT_MAX_DEFER)
    n = len(close)
    for k in range(max_defer + 1):
        j = ei + k
        if j >= n:
            return None
        if pd.isna(close.iloc[j]):
            continue  # 停牌（无数据）
        if is_limit_up(pct.iloc[j], up):
            continue  # 涨停买不到
        return j, float(close.iloc[j])
    return None


def resolve_exit(hist: pd.DataFrame, xi: int, cfg: dict | None = None):
    """从 xi 起找首个可卖出日（非跌停、非停牌）。

    返回 (actual_xi, exit_price)；窗口内都卖不出返回 None。
    """
    if hist is None or xi < 0:
        return None
    close = (pd.to_numeric(hist["收盘"], errors="coerce")
             if "收盘" in hist.columns else pd.Series(dtype=float))
    pct = _pct_series(hist)
    down = (get(cfg, "trading", "limit_down_pct", default=DEFAULT_LIMIT_DOWN)
            if cfg else DEFAULT_LIMIT_DOWN)
    max_defer = (get(cfg, "trading", "max_defer_days", default=DEFAULT_MAX_DEFER)
                 if cfg else DEFAULT_MAX_DEFER)
    n = len(close)
    for k in range(max_defer + 1):
        j = xi + k
        if j >= n:
            return None
        if pd.isna(close.iloc[j]):
            continue  # 停牌
        if is_limit_down(pct.iloc[j], down):
            continue  # 跌停卖不出
        return j, float(close.iloc[j])
    return None
