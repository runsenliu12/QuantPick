"""数据覆盖率诊断：统计生产实际使用的因子在候选池上的取到率。

为什么需要它：
    因子层对取不到的值用 `.fillna(0)` 静默当中性处理。当 AKShare 免费接口
    大量取不到 PE/PB/ROE（很常见）时，策略**表面跑着质量/价值因子，实际只剩
    动量+资金流在起作用**——所谓"多因子"是空转。覆盖率低时应当切换数据源或
    下调失效因子的权重，而不是假装有效。

设计：
    - 复用 selection.compute_factor_rows，保证与生产同一套取数/过滤。
    - summarize_coverage 为纯函数，便于单测（无需联网）。
    - factor_coverage 对股+ETF 实跑取数并汇总，标出低于阈值的"关键因子"。
"""
from __future__ import annotations

import pandas as pd

from src.config import get
from src import selection

# 生产中真正参与打分的关键因子（顺序即展示顺序）
STOCK_FACTORS = [
    "ret_20", "ret_60", "vol_60",
    "roe", "debt_ratio",
    "pe", "pb", "dividend_yield",
    "fund_flow_5", "fund_flow_20",
]
ETF_FACTORS = [
    "ret_20", "ret_60", "vol_60",
    "aum", "amount",
    "premium", "expense_ratio", "tracking_error",
]
# 这些因子缺失会让"多因子"退化为"单因子"，优先告警
CRITICAL = {"pe", "pb", "roe", "dividend_yield", "expense_ratio", "tracking_error"}


def summarize_coverage(df: pd.DataFrame, columns) -> dict:
    """纯函数：给定含因子列的 DataFrame，返回每列非-null 比例与缺失数。

    n=候选数；factors 每项含 factor/present/missing/coverage(0~1)。
    列不在 df 中时视为 0 覆盖（生产也未取）。
    """
    n = len(df)
    rows = []
    for c in columns:
        if c not in df.columns:
            rows.append({"factor": c, "present": 0, "missing": n, "coverage": 0.0})
            continue
        present = int(df[c].notna().sum())
        rows.append({
            "factor": c,
            "present": present,
            "missing": n - present,
            "coverage": round(present / n, 4) if n else 0.0,
        })
    return {"n": n, "factors": rows}


def factor_coverage(fetcher, cfg: dict) -> dict:
    """对股+ETF 实际跑因子计算，统计覆盖率并对关键因子标阈值告警。

    返回 {stock:{n,factors}, etf:{...}, flags:[str], warn_below:float}
    """
    warn = get(cfg, "coverage", "warn_below", default=0.5)
    out: dict = {}
    by_kind = {"stock": STOCK_FACTORS, "etf": ETF_FACTORS}
    for kind, cols in by_kind.items():
        df = selection.compute_factor_rows(fetcher, cfg, kind)
        present_cols = [c for c in cols if c in df.columns]
        out[kind] = summarize_coverage(df, present_cols)

    flags = []
    for kind, rep in out.items():
        for f in rep["factors"]:
            if f["factor"] in CRITICAL and f["coverage"] < warn:
                flags.append(
                    f"{kind}.{f['factor']} 覆盖率 {f['coverage']:.0%} < {warn:.0%}："
                    f"该因子实际在空转，建议换数据源或下调权重"
                )
    out["warn_below"] = warn
    out["flags"] = flags
    return out


def format_report(rep: dict) -> str:
    """把 factor_coverage 结果渲染成可读文本报告。"""
    lines = ["=== 因子数据覆盖率诊断 ===", ""]
    for kind in ("stock", "etf"):
        if kind not in rep:
            continue
        sub = rep[kind]
        lines.append(f"[{kind}] 候选数 n={sub['n']}")
        lines.append(f"  {'因子':<16}{'取到':>6}{'缺失':>6}{'覆盖率':>9}")
        for f in sub["factors"]:
            lines.append(
                f"  {f['factor']:<16}{f['present']:>6}{f['missing']:>6}{f['coverage']:>8.0%}"
            )
        lines.append("")
    if rep.get("flags"):
        lines.append("⚠️ 关键因子覆盖率偏低（策略可能在空转）：")
        for fl in rep["flags"]:
            lines.append(f"  - {fl}")
    else:
        lines.append("✅ 关键因子覆盖率均达标。")
    return "\n".join(lines)
