"""单方法信号回测（不连接数据源 / 券商）。

把任意 methods 产出的 position 序列接进回测框架，按真实交易约束模拟资金曲线并计算指标。
交易约束建模：
  - T+1        : 当日信号次日才生效（A 股当日买入不能当日卖）。
  - 成本       : 每次换仓按换手率扣佣金 + 滑点。
  - 满仓约束   : position 取值 [-1, +1]，long_only 时把 -1 置 0；单位数(如海龟)自动归一化到 [-1,1]。
  - 不连接任何外部数据，也不下单；方法本身只是纯函数信号。

典型用法：
    from src.methods.backtest_signal import backtest_method
    res = backtest_method("turtle", n=250, seed=7)          # 合成数据演示
    res = backtest_method("dual_ma", params={"fast":5,"slow":20})
    print(res["metrics"])

或手动：
    from src.methods import turtle
    pos = turtle.turtle_signal(high, low, close)
    from src.methods.backtest_signal import signal_backtest, compute_signal_metrics
    out = signal_backtest(close, pos)
    metrics = compute_signal_metrics(out["nav"], out["trades"], out["total_turnover"])
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ---- 方法注册表：name -> (模块属性, 函数名, 默认参数, 是否需要 OHLC) ----
# 仅列出可在合成/真实 close（或 OHLC）上直接跑、且可解释的方法。
_METHOD_REGISTRY = {
    "dual_ma":          ("trend",          "dual_ma_signal",        {"fast": 5, "slow": 20}, False),
    "macd":             ("trend",          "macd_signal",           {"fast": 12, "slow": 26, "signal": 9}, False),
    "breakout":         ("trend",          "breakout_signal",       {"window": 20}, False),
    "ts_mom":           ("momentum",       "momentum_signal",       {"window": 60}, False),
    "zscore_rev":       ("mean_reversion", "zscore_reversion",      {"window": 20, "entry": 2.0, "exit_z": 0.5, "long_only": True}, False),
    "bollinger":        ("mean_reversion", "bollinger_signal",      {"window": 20, "k": 2.0, "long_only": True}, False),
    "rsi":              ("mean_reversion", "rsi_signal",           {"window": 14, "overbought": 70, "oversold": 30, "long_only": True}, False),
    "turtle":           ("turtle",         "turtle_signal",        {"entry": 20, "exit_win": 10, "atr_win": 20, "add_unit": 0.5, "max_units": 4, "long_only": True}, True),
    "multi_timeframe":  ("multi_timeframe","multi_timeframe_signal",{"windows": (5, 20, 60)}, False),
}


def gen_ohlc(n: int = 250, seed: int = 7, vol: float = 0.018, drift: float = 0.0004):
    """合成一条 OHLC（close/high/low）随机游走序列，用于离线演示，不连任何数据。"""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2023-01-01", periods=n, freq="B")
    close = [10.0]
    for _ in range(n - 1):
        ret = drift + rng.normal(0, vol)
        ret = float(np.clip(ret, -0.098, 0.098))
        close.append(close[-1] * (1 + ret))
    close = pd.Series(close, index=dates)
    High, Low = [], []
    for i, c in enumerate(close):
        o = close.iloc[i - 1] if i > 0 else c
        hi = max(o, c) * (1 + abs(rng.normal(0, 0.006)))
        lo = min(o, c) * (1 - abs(rng.normal(0, 0.006)))
        High.append(hi)
        Low.append(lo)
    return close, pd.Series(High, index=dates), pd.Series(Low, index=dates)


def signal_backtest(close, position, cost: float = 0.0008, init_capital: float = 1.0,
                    t1: bool = True, normalize_units: bool = True,
                    long_only: bool | None = None) -> dict:
    """把 position 序列接入回测，返回 nav / trades / 有效持仓 / 总换手。

    close    : 价格序列（Series 或 list）
    position : 与 close 对齐的持仓序列，取值 [&minus;1,+1]；若超出范围且 normalize_units=True 则按最大绝对值缩放
    cost     : 单边成本（佣金+滑点），按换手率计
    t1       : 是否 T+1（信号次日生效）
    long_only: None=沿用 position 符号；True=把负值置 0
    """
    close = pd.Series(close).reset_index(drop=True)
    pos = pd.Series(position).reset_index(drop=True)
    if len(close) != len(pos):
        raise ValueError(f"close 与 position 长度不一致：{len(close)} vs {len(pos)}")

    if normalize_units and pos.abs().max() > 1:
        m = float(pos.abs().max())
        if m > 0:
            pos = pos / m
    if long_only:
        pos = pos.clip(lower=0)

    eff = pos.shift(1) if t1 else pos
    eff = eff.fillna(0.0)

    nav = [float(init_capital)]
    trades = []
    total_turn = 0.0
    prev_eff = float(eff.iloc[0]) if len(eff) else 0.0
    entry_i = None
    entry_sign = 0.0

    for i in range(1, len(close)):
        e = float(eff.iloc[i])
        turn = abs(e - prev_eff)
        if turn > 0:
            nav[-1] *= (1 - cost * turn)
            total_turn += turn
        day_ret = close.iloc[i] / close.iloc[i - 1] - 1
        nav.append(nav[-1] * (1 + prev_eff * day_ret))

        # 交易记录（按有效持仓变化切分）
        if prev_eff == 0 and e != 0:
            entry_i, entry_sign = i, e
        elif prev_eff != 0 and e != prev_eff:
            if entry_i is not None:
                tret = entry_sign * (close.iloc[i] / close.iloc[entry_i] - 1)
                trades.append({"entry": int(entry_i), "exit": int(i),
                               "side": 1 if entry_sign > 0 else -1, "ret": float(tret)})
            if e == 0:
                entry_i, entry_sign = None, 0.0
            else:
                entry_i, entry_sign = i, e
        prev_eff = e

    # 期末若仍持仓，按最后一根收盘价平仓，计入交易统计（不影响已算净值）
    if entry_i is not None:
        last = len(close) - 1
        tret = entry_sign * (close.iloc[last] / close.iloc[entry_i] - 1)
        trades.append({"entry": int(entry_i), "exit": int(last),
                       "side": 1 if entry_sign > 0 else -1, "ret": float(tret)})

    return {"nav": pd.Series(nav), "trades": trades,
            "eff_position": eff, "total_turnover": float(total_turn)}


def compute_signal_metrics(nav, trades, total_turnover: float) -> dict:
    """由 nav / trades / 总换手计算绩效指标。"""
    nav = pd.Series(nav).reset_index(drop=True).dropna()
    if len(nav) < 2:
        return {}
    rets = nav.pct_change().dropna()
    total = nav.iloc[-1] - 1
    n = len(nav) - 1
    years = n / 252.0
    ann = (1 + total) ** (1 / years) - 1 if years > 0 else 0.0
    sharpe = rets.mean() / rets.std() * np.sqrt(252) if rets.std() > 0 else 0.0
    mdd = float((nav / nav.cummax() - 1).min())
    wins = [t for t in trades if t.get("ret", 0) > 0]
    win_rate = len(wins) / len(trades) if trades else 0.0
    return {
        "total_return": float(total),
        "annual_return": float(ann),
        "sharpe": float(sharpe),
        "max_drawdown": mdd,
        "vol_annual": float(rets.std() * np.sqrt(252)),
        "num_trades": len(trades),
        "win_rate": float(win_rate),
        "total_turnover": float(total_turnover),
    }


def _resolve_method(method_name: str):
    """按方法名取得可调用对象与默认参数、是否需要 OHLC。"""
    if method_name not in _METHOD_REGISTRY:
        raise KeyError(f"未知方法 '{method_name}'，可选：{sorted(_METHOD_REGISTRY)}")
    mod_attr, func_name, defaults, needs_ohlc = _METHOD_REGISTRY[method_name]
    mod = __import__(f"src.methods.{mod_attr}", fromlist=[mod_attr])
    return getattr(mod, func_name), defaults, needs_ohlc


def _ml_position(close: pd.Series, params: dict):
    """机器学习择时：合成特征 X 与标签 y，调用 ml_timing_signal。"""
    from . import ml_timing
    lookahead = int(params.get("lookahead", 5))
    kind = params.get("kind", "logreg")
    ret = close.pct_change().fillna(0.0)
    feats = pd.DataFrame({
        "r1": ret.shift(1),
        "r2": ret.shift(2),
        "r5": ret.shift(5),
        "r10": ret.shift(10),
    }).dropna()
    feats = feats.iloc[:-lookahead]  # 留出标签窗口
    fwd = close.shift(-lookahead) / close - 1
    y = (fwd.loc[feats.index] > 0).astype(int).values
    X = feats.values
    sig = ml_timing.ml_timing_signal(X, y, lookahead=lookahead, kind=kind)
    out = pd.Series(0.0, index=close.index)
    out.loc[feats.index] = sig.values
    return out.fillna(0.0)


def run_method_on_prices(method_name: str, close=None, high=None, low=None,
                         params: dict | None = None, n: int = 250, seed: int = 7):
    """生成（或接收）行情，计算指定方法的 position 序列。

    返回 (position: pd.Series, close: pd.Series)。
    """
    if close is None:
        c, h, l = gen_ohlc(n=n, seed=seed)
        close, high, low = c, h, l
    else:
        close = pd.Series(close).reset_index(drop=True)
        if high is not None:
            high = pd.Series(high).reset_index(drop=True)
        if low is not None:
            low = pd.Series(low).reset_index(drop=True)

    params = dict(params or {})

    if method_name == "ml_timing":
        pos = _ml_position(close, params)
        return pos, close

    func, defaults, needs_ohlc = _resolve_method(method_name)
    kw = {**defaults, **params}

    if needs_ohlc:
        if high is None or low is None:
            _, high, low = gen_ohlc(n=len(close), seed=seed)
        pos = func(high, low, close, **kw)
    else:
        pos = func(close, **kw)
    return pd.Series(pos).reset_index(drop=True), close


def backtest_method(method_name: str, close=None, high=None, low=None,
                    params: dict | None = None, cost: float = 0.0008,
                    t1: bool = True, n: int = 250, seed: int = 7,
                    long_only: bool | None = None) -> dict:
    """端到端：选方法 -> 算信号 -> 回测 -> 指标，返回完整结果字典。"""
    pos, close = run_method_on_prices(method_name, close=close, high=high, low=low,
                                      params=params, n=n, seed=seed)
    out = signal_backtest(close, pos, cost=cost, t1=t1, long_only=long_only)
    metrics = compute_signal_metrics(out["nav"], out["trades"], out["total_turnover"])
    return {
        "method": method_name,
        "params": params or {},
        "position": pos,
        "close": close,
        "nav": out["nav"],
        "trades": out["trades"],
        "eff_position": out["eff_position"],
        "total_turnover": out["total_turnover"],
        "metrics": metrics,
    }


def list_methods() -> list:
    """返回支持的方法名列表（含 ml_timing）。"""
    return sorted(list(_METHOD_REGISTRY) + ["ml_timing"])
