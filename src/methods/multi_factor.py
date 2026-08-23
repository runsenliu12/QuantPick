"""多因子合成（通用版，与 src/selection 思路一致）。

把多个单因子打分合成一个横截面排序，用于选股/加权。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import normalize_weights


def zscore_panel(values: pd.DataFrame) -> pd.DataFrame:
    """对每列（因子）做横截面 z-score 标准化，消除量纲与分布差异。"""
    return values.sub(values.mean(axis=0), axis=1).div(values.std(axis=0).replace(0, np.nan))


def combine_scores(scores: dict, weights: dict = None):
    """多因子合成：各因子 z-score 后按权重加权，返回合成分数（降序）。

    scores: {factor_name: pd.Series(横截面, index=asset)}
    weights: {factor_name: float}，缺省等权。
    """
    names = list(scores.keys())
    mat = pd.concat([scores[n] for n in names], axis=1)
    mat.columns = names
    z = zscore_panel(mat)
    if weights is None:
        wvec = pd.Series(1.0 / len(names), index=names)
    else:
        wvec = pd.Series(weights).reindex(names).fillna(0.0)
        wvec = wvec / wvec.sum() if wvec.sum() > 0 else wvec
    combined = z.mul(wvec, axis=1).sum(axis=1)
    return combined.sort_values(ascending=False)
