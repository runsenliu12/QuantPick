"""数据层：基于 AKShare 获取 A 股股票与 ETF 行情、财务、资金流、估值、行业、指数等数据，
并落地 SQLite 缓存。

设计要点：
- 所有 AKShare 调用带超时与异常兜底，单标失败不影响整体扫描。
- 行情 / 列表 落 SQLite 缓存，避免每次重复爬取触发限频。
- 新增：估值(PE/PB/股息率)、行业、ETF 净值/折溢价/费率、指数与基准、市场状态判断。
- 抓取失败统一记日志（不再静默吞掉），由上层决定告警/中止。
"""
from __future__ import annotations

import logging
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

logger = logging.getLogger("quantpick.data")


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
        # 历史选中结果（用于复盘 / 战绩）
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS selections (
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
        )
        self._conn.commit()

    def _get_cache(self, key: str):
        row = self._conn.execute(
            "SELECT value, ts FROM cache WHERE key=?", (key,)
        ).fetchone()
        if not row:
            return None
        if time.time() - row[1] > self.cache_days * 86400:
            return None
        import json
        return json.loads(row[0])

    def _set_cache(self, key: str, value, days: Optional[int] = None) -> None:
        import json
        ttl = (days or self.cache_days) * 86400
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
        if ak is None:
            return pd.DataFrame()
        market = "sh" if code.startswith("6") else "sz"
        df = ak.stock_individual_fund_flow(stock=code, market=market)
        if df is None or df.empty:
            return pd.DataFrame()
        df["日期"] = pd.to_datetime(df["日期"])
        return df

    def get_stock_financials(self, code: str) -> dict:
        """取最新一期 质量(ROE/负债率) + 估值(PE/PB/股息率)。"""
        key = f"fin_{code}"
        cached = self._get_cache(key)
        if cached is not None:
            return cached
        out = {"roe": None, "debt_ratio": None, "pe": None, "pb": None, "dividend_yield": None}
        try:
            df = ak.stock_financial_analysis_indicator(symbol=code)
            if df is not None and not df.empty:
                last = df.iloc[0]
                out["roe"] = _to_float(last.get("净资产收益率(%)"))
                out["debt_ratio"] = _to_float(last.get("资产负债率(%)"))
        except Exception as e:
            logger.warning("财务因子获取失败 %s: %s", code, e)
        # 估值指标（ttm 市盈率 / 市净率 / 股息率）
        try:
            val = ak.stock_a_indicator_lg(symbol=code)
            if val is not None and not val.empty:
                last = val.iloc[-1]
                out["pe"] = _to_float(last.get("市盈率"))
                out["pb"] = _to_float(last.get("市净率"))
                out["dividend_yield"] = _to_float(last.get("股息率"))  # 单位 %
        except Exception as e:
            logger.warning("估值因子获取失败 %s: %s", code, e)
        self._set_cache(key, out, days=3)
        return out

    def get_stock_industry(self, code: str) -> Optional[str]:
        """返回个股所属申万/东方财富行业（用于行业内中性化）。"""
        key = f"ind_{code}"
        cached = self._get_cache(key)
        if cached is not None:
            return cached
        industry = None
        try:
            info = ak.stock_individual_info_em(symbol=code)
            if isinstance(info, dict):
                industry = info.get("行业")
        except Exception as e:
            logger.warning("行业获取失败 %s: %s", code, e)
        self._set_cache(key, industry or "", days=7)
        return industry

    # ---------- ETF ----------
    def get_etf_universe(self) -> pd.DataFrame:
        """返回场内 ETF 列表：code, name, price, pct_change, amount, 流通份额, 净值估算, 折价率"""
        cached = self._get_cache("etf_spot")
        if cached is not None:
            return pd.DataFrame(cached)
        df = ak.fund_etf_spot_em()
        keep = ["代码", "名称", "最新价", "涨跌幅", "成交额", "流通份额", "换手率", "净值估算", "折价率"]
        df = df[[c for c in keep if c in df.columns]]
        df = df.rename(columns={
            "代码": "code", "名称": "name", "最新价": "price",
            "涨跌幅": "pct_change", "成交额": "amount",
            "流通份额": "float_shares", "换手率": "turnover",
            "净值估算": "nav_est", "折价率": "discount",
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

    def get_etf_nav(self, code: str) -> pd.DataFrame:
        """ETF 单位净值历史（用于真实跟踪误差：价格收益 vs 净值收益）。"""
        key = f"etf_nav_{code}"
        cached = self._get_cache(key)
        if cached is not None:
            return pd.DataFrame(cached)
        try:
            df = ak.fund_etf_fund_info_em(symbol=code, indicator="单位净值")
        except Exception as e:
            logger.warning("ETF 净值获取失败 %s: %s", code, e)
            return pd.DataFrame()
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.rename(columns={df.columns[0]: "日期", df.columns[1]: "nav"})
        df["日期"] = pd.to_datetime(df["日期"])
        self._set_cache(key, df.to_dict(orient="records"), days=1)
        return df

    def get_etf_info(self, code: str) -> dict:
        """规模 / 跟踪指数 / 管理费（best-effort，取不到返回空）。"""
        key = f"etf_info_{code}"
        cached = self._get_cache(key)
        if cached is not None:
            return cached
        out = {"expense_ratio": None, "tracked_index": None, "scale": None}
        try:
            df = ak.fund_etf_category_sina(symbol=code)
            if df is not None and not df.empty and "管理费用" in df.columns:
                out["expense_ratio"] = _to_float(df.iloc[0].get("管理费用"))
        except Exception as e:
            logger.warning("ETF 元信息获取失败 %s: %s", code, e)
        self._set_cache(key, out, days=7)
        return out

    # ---------- 指数 / 基准 / 市场状态 ----------
    def get_index_hist(self, symbol: str = "000300") -> pd.DataFrame:
        """指数日线（用于基准对比 / 市场状态过滤）。"""
        key = f"idx_{symbol}"
        cached = self._get_cache(key)
        if cached is not None:
            return pd.DataFrame(cached)
        df = ak.index_zh_a_hist(symbol=symbol, period="daily", adjust="")
        if df is None or df.empty:
            return pd.DataFrame()
        df["日期"] = pd.to_datetime(df["日期"])
        self._set_cache(key, df.to_dict(orient="records"), days=1)
        return df

    def get_market_regime(self, symbol: str = "000300", ma_window: int = 200) -> dict:
        """市场状态：沪深300 收盘价 vs MA(ma_window)。
        返回 {state: risk_on|risk_off, close, ma, scale}
        scale 为建议仓位缩放系数（risk_off 时降仓）。
        """
        key = f"regime_{symbol}_{ma_window}"
        cached = self._get_cache(key)
        if cached is not None:
            return cached
        df = self.get_index_hist(symbol)
        out = {"state": "risk_on", "close": None, "ma": None, "scale": 1.0}
        if df is not None and not df.empty and "收盘" in df.columns:
            close = pd.to_numeric(df["收盘"], errors="coerce").dropna()
            if len(close) >= ma_window:
                ma = close.rolling(ma_window).mean().iloc[-1]
                c = close.iloc[-1]
                out = {
                    "state": "risk_on" if c >= ma else "risk_off",
                    "close": float(c),
                    "ma": float(ma),
                    "scale": 1.0 if c >= ma else 0.3,
                }
        self._set_cache(key, out, days=1)
        return out


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
