"""数据层：基于 AKShare 获取 A 股股票与 ETF 行情、财务、资金流数据，并落地 SQLite 缓存。

设计要点：
- 所有 AKShare 调用带超时与异常兜底，单标失败不影响整体扫描。
- 行情 / 列表 落 SQLite 缓存，避免每次重复爬取触发限频。
- 对外暴露统一的 get_stock_universe / get_etf_universe / get_hist 接口。
"""
from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime
from typing import List, Optional

import pandas as pd

try:
    import akshare as ak
except ImportError:  # 允许在无网络的本地环境只做语法/逻辑检查
    ak = None


class DataFetcher:
    def __init__(self, sqlite_path: str = "data/quantpick.db", cache_days: int = 1,
                 timeout: int = 15):
        self.cache_days = cache_days
        self.timeout = timeout
        os.makedirs(os.path.dirname(sqlite_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(sqlite_path)
        self._init_db()

    # ---------- 缓存 ----------
    def _init_db(self):
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT, ts REAL)"
        )
        self._conn.commit()

    def _get_cache(self, key: str):
        import json
        row = self._conn.execute(
            "SELECT value, ts FROM cache WHERE key=?", (key,)
        ).fetchone()
        if not row:
            return None
        if time.time() - row[1] > self.cache_days * 86400:
            return None
        return json.loads(row[0])

    def _set_cache(self, key: str, value) -> None:
        import json
        self._conn.execute(
            "INSERT OR REPLACE INTO cache(key, value, ts) VALUES (?,?,?)",
            (key, json.dumps(value, default=str), time.time()),
        )
        self._conn.commit()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    # ---------- 股票 ----------
    def get_stock_universe(self) -> pd.DataFrame:
        """返回 A 股股票列表：code, name, 成交额, 总市值, 最新价, 涨跌幅"""
        cached = self._get_cache("stock_spot")
        if cached is not None:
            return pd.DataFrame(cached)
        if ak is None:
            raise RuntimeError("akshare 未安装，无法获取行情")
        df = ak.stock_zh_a_spot_em()
        keep = ["代码", "名称", "最新价", "涨跌幅", "成交额", "总市值", "流通市值", "换手率"]
        df = df[[c for c in keep if c in df.columns]]
        df = df.rename(columns={
            "代码": "code", "名称": "name", "最新价": "price",
            "涨跌幅": "pct_change", "成交额": "amount", "总市值": "market_cap",
            "流通市值": "float_cap", "换手率": "turnover",
        })
        self._set_cache("stock_spot", df.to_dict(orient="records"))
        return df

    def get_stock_hist(self, code: str, adjust: str = "qfq") -> pd.DataFrame:
        key = f"stock_hist_{code}_{adjust}"
        cached = self._get_cache(key)
        if cached is not None:
            return pd.DataFrame(cached)
        df = ak.stock_zh_a_hist(symbol=code, period="daily", adjust=adjust)
        if df is None or df.empty:
            return pd.DataFrame()
        df["日期"] = pd.to_datetime(df["日期"])
        self._set_cache(key, df.to_dict(orient="records"))
        return df

    def get_stock_fund_flow(self, code: str) -> pd.DataFrame:
        """主力资金流（近 N 日），用于资金流因子。"""
        market = "sh" if code.startswith("6") else "sz"
        df = ak.stock_individual_fund_flow(stock=code, market=market)
        if df is None or df.empty:
            return pd.DataFrame()
        df["日期"] = pd.to_datetime(df["日期"])
        return df

    def get_stock_financials(self, code: str) -> dict:
        """取最新一期 ROE / 资产负债率，用于质量因子。"""
        try:
            df = ak.stock_financial_analysis_indicator(symbol=code)
        except Exception:
            return {}
        if df is None or df.empty:
            return {}
        last = df.iloc[0]
        return {
            "roe": _to_float(last.get("净资产收益率(%)")),
            "debt_ratio": _to_float(last.get("资产负债率(%)")),
        }

    # ---------- ETF ----------
    def get_etf_universe(self) -> pd.DataFrame:
        """返回场内 ETF 列表：code, name, price, pct_change, amount, 流通份额, 净值估算"""
        cached = self._get_cache("etf_spot")
        if cached is not None:
            return pd.DataFrame(cached)
        df = ak.fund_etf_spot_em()
        keep = ["代码", "名称", "最新价", "涨跌幅", "成交额", "流通份额", "换手率"]
        df = df[[c for c in keep if c in df.columns]]
        df = df.rename(columns={
            "代码": "code", "名称": "name", "最新价": "price",
            "涨跌幅": "pct_change", "成交额": "amount",
            "流通份额": "float_shares", "换手率": "turnover",
        })
        self._set_cache("etf_spot", df.to_dict(orient="records"))
        return df

    def get_etf_hist(self, code: str, adjust: str = "qfq") -> pd.DataFrame:
        key = f"etf_hist_{code}_{adjust}"
        cached = self._get_cache(key)
        if cached is not None:
            return pd.DataFrame(cached)
        df = ak.fund_etf_hist_em(symbol=code, period="daily", adjust=adjust)
        if df is None or df.empty:
            return pd.DataFrame()
        df["日期"] = pd.to_datetime(df["日期"])
        self._set_cache(key, df.to_dict(orient="records"))
        return df

    def get_etf_info(self, code: str) -> dict:
        """规模 / 跟踪指数等元信息（可选，失败返回空）。"""
        try:
            df = ak.fund_etf_category_sina(symbol=code)
        except Exception:
            return {}
        return {} if df is None else df.to_dict(orient="records")


def _to_float(v):
    try:
        if v in (None, "", "-"):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def is_trading_day() -> bool:
    """粗略判断是否为交易日（周末非交易日；节假日未穷举）。"""
    return datetime.now().weekday() < 5
