"""历史选中留存：把每次扫描的候选清单写入 SQLite，用于长期复盘与战绩展示。

与 data.py 共用同一字段约定（selections 表），独立连接以便 server / scan 各自调用。
"""
from __future__ import annotations

import os
import sqlite3
from typing import List, Optional

import pandas as pd


_SCHEMA = """CREATE TABLE IF NOT EXISTS selections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date TEXT,
    kind TEXT,
    code TEXT,
    name TEXT,
    rank INTEGER,
    score REAL,
    position_pct REAL,
    stop_loss_pct REAL,
    factors TEXT
)"""


def _conn(path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    c = sqlite3.connect(path)
    c.execute(_SCHEMA)
    return c


def save_run(path: str, run_date: str, kind: str, df) -> int:
    """写入一次扫描结果（df 至少含 code/rank/score/position_pct/stop_loss_pct）。返回写入条数。"""
    if df is None or df.empty:
        return 0
    conn = _conn(path)
    n = 0
    try:
        for _, r in df.iterrows():
            factors_json = ""
            try:
                import json
                cols = [c for c in df.columns if c.startswith("c_") or c in
                        ("ret_20", "ret_60", "roe", "pe", "pb", "dividend_yield",
                         "fund_flow_5", "fund_flow_20", "aum", "expense_ratio",
                         "tracking_error", "premium", "industry")]
                factors_json = json.dumps({c: r.get(c) for c in cols}, default=str, ensure_ascii=False)
            except Exception:
                pass
            conn.execute(
                """INSERT INTO selections
                   (run_date, kind, code, name, rank, score, position_pct, stop_loss_pct, factors)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (run_date, kind, str(r.get("code")), r.get("name"),
                 int(r.get("rank", 0) or 0), float(r.get("score", 0) or 0),
                 float(r.get("position_pct", 0) or 0), float(r.get("stop_loss_pct", 0) or 0),
                 factors_json),
            )
            n += 1
        conn.commit()
    finally:
        conn.close()
    return n


def load_history(path: str, limit: int = 500) -> List[dict]:
    conn = _conn(path)
    try:
        rows = conn.execute(
            "SELECT run_date, kind, code, name, rank, score, position_pct, stop_loss_pct "
            "FROM selections ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    finally:
        conn.close()
    return [
        {"run_date": r[0], "kind": r[1], "code": r[2], "name": r[3],
         "rank": r[4], "score": r[5], "position_pct": r[6], "stop_loss_pct": r[7]}
        for r in rows
    ]


def load_latest_run(path: str, kind: str | None = None) -> pd.DataFrame:
    """读取最近一次 run_date 的选中清单（用于换手率控制的上一期对比）。"""
    conn = _conn(path)
    try:
        row = conn.execute("SELECT MAX(run_date) FROM selections").fetchone()
        if not row or row[0] is None:
            return pd.DataFrame()
        rd = row[0]
        q = ("SELECT run_date, kind, code, name, rank, score, position_pct, stop_loss_pct "
             "FROM selections WHERE run_date=?")
        params = [rd]
        if kind:
            q += " AND kind=?"
            params.append(kind)
        rows = conn.execute(q, params).fetchall()
    finally:
        conn.close()
    return pd.DataFrame(rows, columns=["run_date", "kind", "code", "name",
                                       "rank", "score", "position_pct", "stop_loss_pct"])
