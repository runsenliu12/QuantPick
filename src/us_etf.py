"""美股 ETF 选基脚手架（默认关闭，需 yfinance）。

设计要点：
- 通过 yfinance 拉取美股 ETF 价格 / 规模 / 费率，复用 A 股 ETF 的因子框架
  （动量 / 流动性 / 折溢价代理 / 规模 / 费率），产出与 A 股候选同 schema 的清单。
- 默认不启用：config.json 中 us_etf.enabled=false。启用后 daily_scan 会将其作为
  第 3 个候选池（独立 kind="us_etf"，不影响 A 股风控与组合）。
- 美股无 A 股式净值估算接口，折溢价用「现价 vs 52 周高点」的折扣代理；
  真实跟踪误差在 yfinance 侧不易取得，暂以波动率代理，后续可接 NAV 数据源。
- yfinance 未安装 / 网络失败时自动回退到 _demo_us_etfs 合成数据，便于无依赖
  自测与展示（demo 数据不参与真实决策，仅用于跑通链路与看板展示）。
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from src.config import get
from src.risk import portfolio_weights, _vol_stop

logger = logging.getLogger("quantpick.us_etf")

DEFAULT_SYMBOLS = ["SPY", "QQQ", "IWM", "VTI", "GLD", "TLT", "ARKK", "VNQ", "EEM", "XLF"]
DEFAULT_WEIGHTS = {
    "momentum": 0.35,
    "liquidity": 0.20,
    "scale": 0.15,
    "premium": 0.10,
    "expense": 0.20,
}


def _load_yf():
    """惰性导入 yfinance（未安装时返回 None，走合成回退）。"""
    try:
        import yfinance as yf  # noqa: F401
        return yf
    except Exception:
        return None


def compute_us_etf_factors(symbol: str) -> dict | None:
    """用 yfinance 计算单只美股 ETF 因子。失败 / 取数不足返回 None。"""
    yf = _load_yf()
    if yf is None:
        return None
    try:
        t = yf.Ticker(symbol)
        hist = t.history(period="1y", interval="1d", auto_adjust=False)
        if hist is None or hist.empty or "Close" not in hist.columns:
            return None
        close = pd.to_numeric(hist["Close"], errors="coerce").dropna()
        if len(close) < 30:
            return None
        ret_20 = float((close.iloc[-1] / close.iloc[-21] - 1) * 100)
        ret_60 = float((close.iloc[-1] / close.iloc[-61] - 1) * 100) if len(close) > 61 else ret_20
        rets = np.log(close.iloc[-60:] / close.iloc[-60:].shift(1)).dropna()
        vol_60 = float(rets.std() * np.sqrt(252) * 100) if len(rets) > 5 else None
        vol = vol_60 if vol_60 is not None else 15.0
        amount = float(close.iloc[-1] * (hist.get("Volume", pd.Series(0, index=hist.index)).iloc[-1] or 0))
        # 52 周折扣作为折溢价代理：现价越接近高点，折扣约接近 0（偏离大=折溢价风险高）
        hi = close.max()
        premium = float(close.iloc[-1] / hi - 1) if hi > 0 else 0.0
        info = {}
        try:
            info = t.info or {}
        except Exception:
            info = {}
        expense = info.get("expenseRatio")
        aum = info.get("totalAssets")
        return {
            "code": symbol,
            "name": info.get("shortName") or symbol,
            "ret_20": ret_20,
            "ret_60": ret_60,
            "vol_60": vol,
            "amount": amount,
            "premium": premium,
            "expense_ratio": float(expense) if expense else None,
            "aum": float(aum) if aum else None,
        }
    except Exception as e:
        logger.warning("美股 ETF %s 取数失败: %s", symbol, e)
        return None


def _zscore(s: pd.Series) -> pd.Series:
    s = pd.to_numeric(s, errors="coerce")
    m, sd = s.mean(), s.std()
    if sd and not np.isnan(sd):
        return (s - m) / sd
    return pd.Series(0.0, index=s.index)


def _score(df: pd.DataFrame, cfg: dict) -> pd.Series:
    """与 A 股 ETF 同思路的线性加权（z-score 后合成），并产出 c_* 因子贡献列。"""
    w = get(cfg, "us_etf", "weights", default=DEFAULT_WEIGHTS) or DEFAULT_WEIGHTS
    mom = 0.5 * _zscore(df["ret_20"]) + 0.5 * _zscore(df["ret_60"].fillna(df["ret_20"]))
    liq = _zscore(df["amount"].fillna(0))
    scale = _zscore(df["aum"].fillna(0))
    # 折溢价代理：偏离 0 越远越差 -> 取 -|premium| 再 z
    prem = _zscore((-pd.to_numeric(df["premium"], errors="coerce").abs()).fillna(0))
    exp = _zscore((-pd.to_numeric(df["expense_ratio"], errors="coerce")).fillna(0))
    comps = {
        "momentum": mom,
        "liquidity": liq,
        "scale": scale,
        "premium": prem,
        "expense": exp,
    }
    score = pd.Series(0.0, index=df.index)
    for k, c in comps.items():
        df[f"c_{k}"] = (float(w.get(k, 0)) * c.fillna(0.0)).round(4)
        score = score + df[f"c_{k}"]
    return (score - score.mean()).round(4)  # 居中，便于跨期对比


def _finalize_us(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    df = df.copy()
    df["score"] = _score(df, cfg)
    rp = get(cfg, "portfolio", "max_position_pct", default=0.12)
    sl_min = get(cfg, "risk", "min_stop_loss_pct", default=0.05)
    sl_max = get(cfg, "risk", "max_stop_loss_pct", default=0.15)
    sl_mult = get(cfg, "risk", "stop_vol_multiplier", default=0.5)
    if "vol_60" in df.columns:
        df["position_pct"] = portfolio_weights(df["vol_60"], cfg, rp).round(4).values
        df["stop_loss_pct"] = _vol_stop(df["vol_60"], sl_min, sl_max, sl_mult)
    else:
        df["position_pct"] = rp
        df["stop_loss_pct"] = sl_min
    return df


def _demo_us_etfs(symbols, cfg, top_n) -> pd.DataFrame:
    """合成演示数据（确定性 RNG），仅用于无依赖自测 / 看板展示。"""
    rng = np.random.default_rng(42)
    rows = []
    for sym in symbols:
        rows.append({
            "code": sym, "name": sym,
            "ret_20": float(rng.normal(2, 4)),
            "ret_60": float(rng.normal(5, 8)),
            "vol_60": float(abs(rng.normal(15, 5)) + 5),
            "amount": float(rng.uniform(1e8, 5e9)),
            "premium": float(rng.normal(0, 0.02)),
            "expense_ratio": float(abs(rng.normal(0.003, 0.002))),
            "aum": float(rng.uniform(1e9, 5e11)),
        })
    df = pd.DataFrame(rows)
    df = _finalize_us(df, cfg)
    df = df.sort_values("score", ascending=False).head(top_n).reset_index(drop=True)
    df["rank"] = df.index + 1
    return df


def rank_us_etfs(cfg: dict, demo: bool = False) -> pd.DataFrame | None:
    """美股 ETF 选基主入口。

    返回与 A 股候选同 schema 的 DataFrame（code/name/rank/score/position_pct/
    stop_loss_pct + 因子列），或 None（未启用且非 demo）。
    """
    enabled = get(cfg, "us_etf", "enabled", default=False)
    if not enabled and not demo:
        return None
    symbols = get(cfg, "us_etf", "symbols", default=DEFAULT_SYMBOLS)
    top_n = get(cfg, "us_etf", "top_n", default=5)

    if demo:
        return _demo_us_etfs(symbols, cfg, top_n)

    if _load_yf() is None:
        logger.warning("yfinance 未安装/不可用，回退到合成演示数据（不参与真实决策）")
        return _demo_us_etfs(symbols, cfg, top_n)

    rows = []
    for sym in symbols:
        f = compute_us_etf_factors(sym)
        if f:
            rows.append(f)
    if not rows:
        logger.warning("美股 ETF 取数全失败，回退合成演示")
        return _demo_us_etfs(symbols, cfg, top_n)

    df = pd.DataFrame(rows)
    df = _finalize_us(df, cfg)
    df = df.sort_values("score", ascending=False).head(top_n).reset_index(drop=True)
    df["rank"] = df.index + 1
    return df


def build_us_report(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return ""
    lines = ["\n【美股 ETF Top】"]
    for _, r in df.iterrows():
        pos = float(r.get("position_pct", 0) or 0) * 100
        sl = float(r.get("stop_loss_pct", 0) or 0) * 100
        name = r.get("name") or r.get("code")
        lines.append(f"{int(r['rank'])}. {name}({r.get('code')}) 分 {r['score']:.2f} 仓 {pos:.1f}% 止损 {sl:.1f}%")
    return "\n".join(lines)
