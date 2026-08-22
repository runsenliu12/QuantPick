"""ML 打分：用最轻量的方式做可解释、防未来函数的因子合成。

为什么不用 sklearn / lightgbm：
    保持零第三方重依赖（CI 只装 pandas/numpy/pytest），且 walk-forward
    逻辑透明、易审计。如环境装了 lightgbm，可后续替换 _ridge_fit 为树模型。

核心防泄漏设计：
    walk_forward_panel 严格按时间扩张窗口——预测第 d 日仅使用 <d 日的全部
    截面数据训练，绝不使用 d 日及之后的任何信息。标签由 make_labels 用
    shift(-h) 生成（后向收益），同样不含未来函数。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _ridge_fit(X: np.ndarray, y: np.ndarray, alpha: float = 1.0):
    """岭回归闭式解（普通方程 + L2），返回权重或 None（样本不足/奇异）。"""
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    m = ~(np.isnan(X).any(axis=1) | np.isnan(y))
    X, y = X[m], y[m]
    if X.shape[0] < X.shape[1] + 2:
        return None
    n = X.shape[1]
    A = X.T @ X + alpha * np.eye(n)
    b = X.T @ y
    try:
        return np.linalg.solve(A, b)
    except np.linalg.LinAlgError:
        return None


def walk_forward_panel(X: np.ndarray, y: np.ndarray, alpha: float = 1.0, warmup: int = 60):
    """逐日扩张窗口打分。X:(n_dates,n_codes,n_feat) y:(n_dates,n_codes)。

    返回同形分数矩阵，warmup 之前的日期为 NaN（训练样本不足）。
    """
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    n_d = X.shape[0]
    scores = np.full((n_d, X.shape[1]), np.nan)
    for d in range(warmup, n_d):
        Xtr = X[:d].reshape(-1, X.shape[2])
        ytr = y[:d].reshape(-1)
        w = _ridge_fit(Xtr, ytr, alpha)
        if w is None:
            continue
        Xd = X[d]
        m = ~np.isnan(Xd).any(axis=1)
        sc = np.full(Xd.shape[0], np.nan)
        sc[m] = Xd[m] @ w
        scores[d] = sc
    return scores


def make_labels(returns: pd.DataFrame, horizon: int = 20) -> pd.DataFrame:
    """由日收益矩阵生成后向累计收益标签（shift(-h)），不含未来函数。"""
    fwd = (1 + returns).rolling(horizon).apply(lambda s: float(np.prod(s)) - 1, raw=True).shift(-horizon)
    return fwd


def ml_score(factor_panels: dict, returns: pd.DataFrame, horizon: int = 20,
             alpha: float = 1.0, warmup: int = 60) -> pd.DataFrame:
    """对多因子面板做 walk-forward ML 打分，返回 date×code 分数矩阵。

    factor_panels: {name: date×code DataFrame}；returns: date×code 日收益。
    """
    dates = returns.index
    codes = returns.columns
    if not factor_panels:
        return pd.DataFrame(index=dates, columns=codes)
    panels = {k: v.reindex(index=dates, columns=codes) for k, v in factor_panels.items()}
    X = np.stack([panels[k].values for k in panels], axis=-1)  # (d, c, f)
    labels = make_labels(returns.reindex(index=dates, columns=codes), horizon)
    y = labels.values
    sc = walk_forward_panel(X, y, alpha, warmup)
    return pd.DataFrame(sc, index=dates, columns=codes)
