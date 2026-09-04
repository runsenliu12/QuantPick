"""机器学习择时（方法示例）。

用监督学习模型（逻辑回归 / 随机森林）根据特征预测未来 N 期涨跌方向，
输出择时信号。采用扩张窗口 walk-forward，避免未来函数（用 i 时刻之前的数据训练，预测 i 时刻）。

依赖 scikit-learn（惰性导入，未安装时给出明确提示，不影响其他模块导入）。
本文件仅提供方法，特征工程与标签由调用方准备。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def ml_timing_signal(X: pd.DataFrame, y: pd.Series, lookahead: int = 5,
                     kind: str = "logreg", expand: bool = True, min_train: int = 60):
    """机器学习择时信号。

    参数：
      X         : 特征矩阵（行=样本/时间，含技术指标等）
      y         : 连续未来收益序列（同一索引）；函数内二值化为涨跌标签
      lookahead : 预测未来 lookahead 期收益方向
      kind      : "logreg"（逻辑回归）或 "rf"（随机森林）
      expand    : True=扩张窗口（用截至 i 的全部历史），False=固定长度滚动窗口
      min_train : 训练样本下限，不足时沿用前值
    返回：{-1,0,+1} 信号序列（索引同 X），未来 lookahead 根内为 0。
    """
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.ensemble import RandomForestClassifier
    except ImportError as e:  # pragma: no cover
        raise ImportError("ml_timing 需要 scikit-learn：pip install scikit-learn") from e

    Model = LogisticRegression if kind == "logreg" else RandomForestClassifier
    ybin = (y > 0).astype(int)
    sig = [0.0] * len(X)
    for i in range(lookahead, len(X)):
        if expand:
            Xtr, ytr = X.iloc[:i], ybin.iloc[:i]
        else:
            Xtr, ytr = X.iloc[max(0, i - min_train):i], ybin.iloc[max(0, i - min_train):i]
        if len(ytr.unique()) < 2 or len(Xtr) < min_train:
            sig[i] = sig[i - 1]
            continue
        m = Model(max_iter=200).fit(Xtr, ytr)
        pred = m.predict(X.iloc[[i]])[0]
        sig[i] = 1 if pred > 0 else -1
    return pd.Series(sig, index=X.index)
