"""因子有效性监控：计算各因子的 Rank IC 与 ICIR（信息系数 / 信息系数比率）。

为什么需要：
    多因子模型里"这个因子到底有没有用"不能靠拍脑袋。IC = 因子值与其后
    向收益的截面秩相关系数；ICIR = IC 序列的均值/标准差（稳定性）。
    IC>0 且 ICIR 越高，因子越稳定有效；IC≈0 或 ICIR<0.5 的因子应降级。

设计：
    - 仅依赖 numpy / pandas，无第三方依赖，便于测试与 CI。
    - 全部为纯函数；make_fwd_returns 用 shift(-h) 生成后向收益，天然不含未来函数。
    - demo_ic 提供带已知关系的合成数据，供看板/接口在无真实因子历史时演示。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _spearman(a, b) -> float:
    """单期截面 Spearman 秩相关（无 scipy 依赖）。"""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    mask = ~(np.isnan(a) | np.isnan(b))
    if mask.sum() < 5:
        return np.nan
    ar = np.argsort(np.argsort(a[mask])) + 1.0
    br = np.argsort(np.argsort(b[mask])) + 1.0
    if ar.std() == 0 or br.std() == 0:
        return np.nan
    return float(np.corrcoef(ar, br)[0, 1])


def ic_series(factor: pd.DataFrame, fwd: pd.DataFrame) -> pd.Series:
    """逐期截面 Rank IC。factor / fwd 均为 date×code 的 DataFrame。"""
    dates = factor.index.intersection(fwd.index)
    out = {}
    for d in dates:
        out[d] = _spearman(factor.loc[d].values, fwd.loc[d].values)
    return pd.Series(out)


def summarize(ic: pd.Series) -> dict:
    """由 IC 序列汇总 IC / ICIR / t 值 / 正向占比。"""
    ic = pd.Series(ic).dropna()
    if ic.empty:
        return {"ic": None, "icir": None, "t": None, "pos_ratio": None, "n": 0}
    m = ic.mean()
    s = ic.std()
    icir = m / s if (s and not np.isnan(s) and s > 0) else None
    n = len(ic)
    t = m / (s / np.sqrt(n)) if (s and s > 0) else None
    pos = (ic > 0).mean()
    return {
        "ic": round(float(m), 4),
        "icir": round(float(icir), 4) if icir is not None else None,
        "t": round(float(t), 3) if t is not None else None,
        "pos_ratio": round(float(pos), 4),
        "n": n,
    }


def report(factor_panels: dict, fwd: pd.DataFrame) -> dict:
    """一次计算多个因子的 IC 摘要。factor_panels: {name: date×code DataFrame}。"""
    out = {}
    for name, fp in factor_panels.items():
        out[name] = summarize(ic_series(fp, fwd))
    return out


def make_fwd_returns(returns: pd.DataFrame, horizon: int = 20) -> pd.DataFrame:
    """由日收益矩阵生成后向收益（shift(-h)），不含未来函数。"""
    return returns.shift(-horizon)


def demo_ic(n_codes: int = 30, n_dates: int = 120, seed: int = 0) -> dict:
    """合成演示：effective 因子与后向收益正相关，noise 因子无关。"""
    rng = np.random.default_rng(seed)
    codes = [f"C{i:03d}" for i in range(n_codes)]
    dates = pd.date_range("2024-01-01", periods=n_dates, freq="D")
    base = rng.normal(0, 1, (n_dates, n_codes))
    noise = rng.normal(0, 1, (n_dates, n_codes))
    f_eff = pd.DataFrame(base, index=dates, columns=codes)
    f_noise = pd.DataFrame(noise, index=dates, columns=codes)
    fwd = pd.DataFrame(base * 0.1 + rng.normal(0, 0.02, (n_dates, n_codes)),
                       index=dates, columns=codes)
    return {"effective": f_eff, "noise": f_noise}, fwd
