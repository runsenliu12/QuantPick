"""纸上交易闭环（Paper Trading Reconciliation）。

把 daily_scan 写入历史的每日推荐，与后续真实行情对账，回答一个最关键的问题：
**"这套策略到底选得准不准、挣不挣钱？"**

方法（透明、可复现）：
- 对历史每一天的推荐，按推荐日（run_date）次一交易日作为建仓价（entry），
  取 entry 之后 N 个交易日（N=5/20/60）的收盘价作为平仓价（exit），计算持有收益。
- 单笔战绩：命中率（收益>0 占比）、平均/中位数收益、样本数。
- 组合净值：每个推荐日把当天的股+ETF 篮子等权持有 N 日，按其实际交易日窗口
  对齐到统一时间轴，每日收益 = 当日所有"持仓中"篮子的等权平均；净值 = 连乘(1+日收益)。
  基准为沪深300 同期净值（指数本身无需再平衡假设）。
- 指标：总收益、年化、Sharpe、最大回撤、相对基准超额与相关性。

注意：仅做研究复盘，非实盘信号，亦非收益承诺。
"""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from src.config import load_config, get
from src.data import DataFetcher

logger = logging.getLogger("quantpick.performance")

DEFAULT_HORIZONS = (5, 20, 60)


# ---------- 纯函数指标 ----------
def max_drawdown(nav: pd.Series) -> float:
    if nav is None or len(nav) == 0:
        return 0.0
    running_max = nav.cummax()
    dd = nav / running_max - 1.0
    return float(dd.min())


def annualized_sharpe(daily: pd.Series, periods: int = 252) -> float:
    d = pd.to_numeric(daily, errors="coerce").dropna()
    if len(d) < 2:
        return 0.0
    std = d.std()
    if std == 0 or pd.isna(std):
        return 0.0
    return float(d.mean() / std * np.sqrt(periods))


def total_return(nav: pd.Series) -> float:
    if nav is None or len(nav) < 2:
        return 0.0
    return float(nav.iloc[-1] / nav.iloc[0] - 1.0)


# ---------- 历史读取 ----------
def load_selections(db_path: str, limit: int = 20000) -> pd.DataFrame:
    """读取 selections 表（按 id 升序，便于按时间回放）。"""
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS selections (
            id INTEGER PRIMARY KEY AUTOINCREMENT, run_date TEXT, kind TEXT,
            code TEXT, name TEXT, rank INTEGER, score REAL,
            position_pct REAL, stop_loss_pct REAL, factors TEXT)"""
    )
    conn.commit()
    try:
        df = pd.read_sql_query(
            "SELECT id, run_date, kind, code, name, rank, score, position_pct, "
            "stop_loss_pct, factors FROM selections ORDER BY id ASC LIMIT ?",
            conn, params=(limit,),
        )
    finally:
        conn.close()
    return df


def _hist_close(fetcher: DataFetcher, code: str, kind: str) -> Optional[pd.Series]:
    """返回以日期为索引的收盘序列（前复权）。"""
    try:
        hist = (fetcher.get_etf_hist(code)
                if kind == "etf"
                else fetcher.get_stock_hist(code))
    except Exception as e:  # 抓取失败：静默跳过该标的（对账是尽力而为）
        logger.warning("对账行情缺失 %s(%s): %s", code, kind, e)
        return None
    if hist is None or hist.empty or "收盘" not in hist.columns:
        return None
    close = pd.to_numeric(hist["收盘"], errors="coerce").dropna()
    idx = pd.to_datetime(hist["日期"]).values
    if len(close) == 0:
        return None
    s = pd.Series(close.values, index=idx).sort_index()
    return s


# ---------- 主计算 ----------
def compute_performance(db_path: str, cfg: Optional[dict] = None,
                        fetcher: Optional[DataFetcher] = None,
                        horizons=None) -> dict:
    """对账：返回结构化战绩。无历史或无法计算时返回 {empty:True}。"""
    cfg = cfg or load_config()
    horizons = horizons or tuple(get(cfg, "performance", "horizons", default=list(DEFAULT_HORIZONS)))
    horizons = tuple(int(h) for h in horizons)
    max_h = max(horizons)

    df = load_selections(db_path)
    if df.empty:
        return {"empty": True,
                "message": "暂无历史推荐记录，请先运行 scripts/daily_scan.py 生成候选后再对账。"}

    own = fetcher is None
    if own:
        fetcher = DataFetcher(
            sqlite_path=get(cfg, "data", "sqlite_path", default="data/quantpick.db"),
            cache_days=get(cfg, "data", "cache_days", default=1),
        )
    try:
        bench_sym = get(cfg, "benchmark", default="000300")
        bench_hist = fetcher.get_index_hist(bench_sym)
        bench_close = None
        if bench_hist is not None and not bench_hist.empty and "收盘" in bench_hist.columns:
            bc = pd.to_numeric(bench_hist["收盘"], errors="coerce").dropna()
            bench_close = pd.Series(bc.values,
                                    index=pd.to_datetime(bench_hist["日期"]).values).sort_index()

        # 逐条推荐：entry/exit 收益 + 持仓窗口日收益
        rec_rows: List[dict] = []
        baskets: List[dict] = []  # {run_date, daily: Series(日期索引, 日收益)}
        by_kind = {"stock": {h: [] for h in horizons}, "etf": {h: [] for h in horizons}}

        for _, row in df.iterrows():
            kind = str(row["kind"]); code = str(row["code"]); rd = str(row["run_date"])
            close = _hist_close(fetcher, code, kind)
            if close is None:
                continue
            rd_dt = pd.to_datetime(rd)
            mask = close.index >= rd_dt
            if not mask.any():
                continue
            ei = int(np.argmax(mask))  # 建仓日 = 推荐日后首个交易日
            entry = float(close.iloc[ei])
            # 各持有期收益
            per_h = {}
            for h in horizons:
                xi = ei + h
                if xi < len(close):
                    per_h[h] = float(close.iloc[xi]) / entry - 1.0
            # 持仓窗口日收益（长度 max_h），用于组合净值
            last = min(len(close) - 1, ei + max_h)
            if last <= ei:
                continue
            dr = (close / close.shift(1) - 1).iloc[ei + 1:last + 1]
            dr.index = close.index[ei + 1:last + 1]
            rec_rows.append({
                "run_date": rd, "kind": kind, "code": code, "name": row.get("name"),
                "rank": int(row.get("rank") or 0), "score": float(row.get("score") or 0),
                "entry": entry, "per_h": per_h,
            })
            baskets.append({"run_date": rd, "kind": kind, "daily": dr})

        if not rec_rows:
            return {"empty": True,
                    "message": "历史推荐存在，但均无法取到后续行情（数据源不可达或样本过短），暂不能对账。"}

        # 单笔战绩（按持有期）
        per_horizon = {}
        for h in horizons:
            rets = [r["per_h"][h] for r in rec_rows if h in r["per_h"]]
            if rets:
                arr = np.array(rets)
                by_kind_all = {"stock": [], "etf": []}
                for r in rec_rows:
                    if h in r["per_h"]:
                        by_kind_all[r["kind"]].append(r["per_h"][h])
                per_horizon[str(h)] = {
                    "count": len(arr),
                    "win_rate": round(float((arr > 0).mean()) * 100, 1),
                    "mean_return": round(float(arr.mean()) * 100, 2),
                    "median_return": round(float(np.median(arr)) * 100, 2),
                    "best": round(float(arr.max()) * 100, 2),
                    "worst": round(float(arr.min()) * 100, 2),
                    "by_kind": {
                        k: (round(float(np.mean(v)) * 100, 2) if v else None)
                        for k, v in by_kind_all.items()
                    },
                }

        # 组合净值：按交易日窗口对齐，每日 = 持仓篮子等权平均
        nav, bench_nav, nav_dates = _build_nav(baskets, bench_close, horizons)

        # 净值指标
        nav_series = pd.Series(nav, index=pd.to_datetime(nav_dates)) if nav else pd.Series(dtype=float)
        bench_series = pd.Series(bench_nav, index=pd.to_datetime(nav_dates)) if bench_nav else pd.Series(dtype=float)
        nav_daily = nav_series.pct_change().fillna(0)
        bench_daily = bench_series.pct_change().fillna(0)

        n_days = max(len(nav_series) - 1, 1)
        portfolio = {
            "total_return": round(total_return(nav_series) * 100, 2),
            "annualized": round((((1 + total_return(nav_series)) ** (252 / n_days)) - 1) * 100, 2) if n_days > 0 else 0.0,
            "sharpe": round(annualized_sharpe(nav_daily), 2),
            "max_drawdown": round(max_drawdown(nav_series) * 100, 2),
        }
        bench = {
            "total_return": round(total_return(bench_series) * 100, 2),
            "annualized": round((((1 + total_return(bench_series)) ** (252 / n_days)) - 1) * 100, 2) if n_days > 0 else 0.0,
            "sharpe": round(annualized_sharpe(bench_daily), 2),
            "max_drawdown": round(max_drawdown(bench_series) * 100, 2),
        }
        corr = float(nav_daily.corr(bench_daily)) if len(nav_daily) > 2 else None

        # 近期推荐明细（含 20 日结果，未到期标"持仓中"）
        recent = sorted(rec_rows, key=lambda r: r["run_date"], reverse=True)[:20]
        recent_out = [{
            "run_date": r["run_date"], "kind": r["kind"], "code": r["code"],
            "name": r["name"], "rank": r["rank"], "score": round(r["score"], 2),
            "entry": round(r["entry"], 2),
            "ret_5": (round(r["per_h"][5] * 100, 2) if 5 in r["per_h"] else None),
            "ret_20": (round(r["per_h"][20] * 100, 2) if 20 in r["per_h"] else None),
            "ret_60": (round(r["per_h"][60] * 100, 2) if 60 in r["per_h"] else None),
            "status": "matured" if max_h in r["per_h"] else "holding",
        } for r in recent]

        return {
            "empty": False,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "benchmark": bench_sym,
            "benchmark_name": "沪深300" if bench_sym == "000300" else bench_sym,
            "horizons": list(horizons),
            "rec_count": len(rec_rows),
            "basket_count": len(baskets),
            "per_horizon": per_horizon,
            "portfolio": portfolio,
            "benchmark_metrics": bench,
            "excess_return": round((portfolio["total_return"] - bench["total_return"]), 2),
            "correlation": round(corr, 2) if corr is not None else None,
            "nav": {
                "dates": [d.strftime("%Y-%m-%d") for d in nav_series.index] if len(nav_series) else [],
                "strategy": [round(float(x), 4) for x in nav] if nav else [],
                "benchmark": [round(float(x), 4) for x in bench_nav] if bench_nav else [],
            },
            "recent": recent_out,
        }
    finally:
        if own:
            fetcher.close()


def _build_nav(baskets: List[dict], bench_close: Optional[pd.Series], horizons):
    """把各篮子的持仓窗口日收益对齐到统一交易日轴，逐日等权平均得到策略净值；
    基准净值用沪深300 同日收益连乘。返回 (nav_list, bench_list, dates_list)。"""
    if not baskets:
        return [], [], []

    # 统一时间轴：所有篮子窗口的并集（交易日）
    all_dates = pd.DatetimeIndex([])
    for b in baskets:
        all_dates = all_dates.union(b["daily"].index)
    all_dates = all_dates.sort_values()

    # 每个篮子映射到统一轴上的日收益（窗口外为 NaN）
    mat = pd.DataFrame(index=all_dates, columns=range(len(baskets)), dtype=float)
    for i, b in enumerate(baskets):
        s = b["daily"].reindex(all_dates)
        mat.iloc[:, i] = s.values

    # 逐日：持仓篮子等权平均（仅对当日有数据的篮子）
    daily_mean = mat.mean(axis=1, skipna=True).fillna(0.0)
    strat_nav = (1.0 + daily_mean).cumprod()
    strat_nav = strat_nav.where(strat_nav != 0, 1.0)

    # 基准：对齐到同一轴
    if bench_close is not None and len(bench_close) > 1:
        bc = bench_close.reindex(all_dates).ffill().bfill()
        bench_daily = bc / bc.shift(1) - 1
        bench_nav = (1.0 + bench_daily.fillna(0.0)).cumprod()
    else:
        bench_nav = pd.Series(1.0, index=all_dates)

    return list(strat_nav.values), list(bench_nav.values), [d for d in all_dates]


# ---------- 报告输出 ----------
def build_html_report(perf: dict) -> str:
    if perf.get("empty"):
        return f"<html><body style='font-family:sans-serif;padding:40px'>" \
               f"<h2>QuantPick 战绩报告</h2><p>{perf.get('message','暂无数据')}</p>" \
               f"</body></html>"

    def kv_table(rows):
        return "<table class='t'>" + "".join(
            f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in rows) + "</table>"

    ph = perf["per_horizon"]
    ph_rows = ""
    for h, m in ph.items():
        bk = m.get("by_kind", {})
        ph_rows += (f"<tr><td>{h}日</td><td>{m['count']}</td>"
                    f"<td class='{'pos' if m['win_rate']>=50 else 'neg'}'>{m['win_rate']}%</td>"
                    f"<td class='{'pos' if m['mean_return']>=0 else 'neg'}'>{m['mean_return']}%</td>"
                    f"<td>{m['median_return']}%</td>"
                    f"<td>{bk.get('stock')}%</td><td>{bk.get('etf')}%</td></tr>")

    rc = perf["recent"]
    rc_rows = ""
    for r in rc:
        def fmt(v): return f"{v}%" if isinstance(v, (int, float)) else "持仓中"
        cls = lambda v: "" if v is None else ("pos" if v >= 0 else "neg")
        rc_rows += (f"<tr><td>{r['run_date']}</td><td>{r['kind']}</td>"
                    f"<td>{r['code']} {r['name']}</td><td>{r['rank']}</td>"
                    f"<td>{r['score']}</td><td>{r['entry']}</td>"
                    f"<td class='{cls(r['ret_5'])}'>{fmt(r['ret_5'])}</td>"
                    f"<td class='{cls(r['ret_20'])}'>{fmt(r['ret_20'])}</td>"
                    f"<td class='{cls(r['ret_60'])}'>{fmt(r['ret_60'])}</td></tr>")

    p = perf["portfolio"]; b = perf["benchmark_metrics"]
    return f"""<!doctype html><html lang='zh'><head><meta charset='utf-8'>
<title>QuantPick 战绩报告</title>
<style>
 body{{font-family:-apple-system,Segoe UI,Roboto,'Microsoft YaHei',sans-serif;margin:0;background:#f5f7fa;color:#1f2937}}
 .wrap{{max-width:1000px;margin:0 auto;padding:28px}}
 h1{{font-size:22px;margin:0 0 4px}} .sub{{color:#6b7280;font-size:13px;margin-bottom:20px}}
 .grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:22px}}
 .card{{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px}}
 .card .l{{font-size:12px;color:#6b7280}} .card .v{{font-size:22px;font-weight:600;margin-top:4px}}
 .pos{{color:#dc2626}} .neg{{color:#16a34a}}
 table{{width:100%;border-collapse:collapse;background:#fff;border-radius:10px;overflow:hidden;font-size:13px}}
 th,td{{padding:9px 10px;text-align:center;border-bottom:1px solid #eee}}
 th{{background:#f0f2f5;color:#374151;font-weight:600}}
 tr:hover{{background:#fafafa}} .sec{{margin:22px 0 10px;font-size:16px;font-weight:600}}
 .note{{font-size:12px;color:#6b7280;margin-top:18px;line-height:1.6}}
</style></head><body><div class='wrap'>
<h1>QuantPick 纸上交易战绩</h1>
<div class='sub'>生成时间 {perf['generated_at']} · 基准 {perf['benchmark_name']} · 样本 {perf['rec_count']} 条推荐 / {perf['basket_count']} 个推荐日篮子</div>

<div class='grid'>
 <div class='card'><div class='l'>策略总收益</div><div class='v {('pos' if p['total_return']>=0 else 'neg')}'>{p['total_return']}%</div></div>
 <div class='card'><div class='l'>基准总收益</div><div class='v {('pos' if b['total_return']>=0 else 'neg')}'>{b['total_return']}%</div></div>
 <div class='card'><div class='l'>超额收益</div><div class='v {('pos' if perf['excess_return']>=0 else 'neg')}'>{perf['excess_return']}%</div></div>
 <div class='card'><div class='l'>策略 Sharpe</div><div class='v'>{p['sharpe']}</div></div>
 <div class='card'><div class='l'>策略年化</div><div class='v'>{p['annualized']}%</div></div>
 <div class='card'><div class='l'>策略最大回撤</div><div class='v neg'>{p['max_drawdown']}%</div></div>
 <div class='card'><div class='l'>基准最大回撤</div><div class='v neg'>{b['max_drawdown']}%</div></div>
 <div class='card'><div class='l'>与基准相关性</div><div class='v'>{perf['correlation']}</div></div>
</div>

<div class='sec'>分持有期命中率（推荐后 N 日收益）</div>
<table><tr><th>持有期</th><th>样本数</th><th>命中率</th><th>平均收益</th><th>中位数</th><th>股均值</th><th>ETF均值</th></tr>
{ph_rows}</table>

<div class='sec'>近期推荐明细</div>
<table><tr><th>推荐日</th><th>类型</th><th>代码/名称</th><th>排名</th><th>分数</th><th>建仓价</th><th>5日</th><th>20日</th><th>60日</th></tr>
{rc_rows}</table>

<div class='note'>
方法论：建仓价 = 推荐日之后首个交易日收盘价（前复权）；平仓价 = 建仓后 N 个交易日收盘价；
组合净值 = 每个推荐日把当日股+ETF 等权持有 N 日，按实际交易日窗口对齐到统一时间轴，每日收益为当日所有持仓篮子的等权平均后连乘。
本报告为量化研究复盘，非买卖建议，亦非收益承诺。
</div>
</div></body></html>"""


def save_report(perf: dict, out_json: str, out_html: str) -> None:
    os.makedirs(os.path.dirname(out_json) or ".", exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json_dump(perf, f)
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(build_html_report(perf))


def json_dump(obj, f):
    import json
    json.dump(obj, f, ensure_ascii=False, indent=2, default=str)


if __name__ == "__main__":
    # 直接运行：计算并保存报告
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    cfg = load_config()
    db = get(cfg, "data", "sqlite_path", default="data/quantpick.db")
    res = compute_performance(db, cfg)
    if res.get("empty"):
        print("[paper] ", res.get("message"))
    else:
        save_report(res, "data/performance.json", "data/performance.html")
        print(f"[paper] 样本 {res['rec_count']} 条，策略总收益 "
              f"{res['portfolio']['total_return']}%，基准 {res['benchmark_metrics']['total_return']}%，"
              f"已保存 data/performance.json / data/performance.html")
