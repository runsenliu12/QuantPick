"""策略画像：从 config.json 抽取可读的"策略画像"，供 Web 看板与 API 展示。

仅依赖标准库，不引入 flask / numpy / akshare，便于独立测试与复用。
"""
from __future__ import annotations


def _pct(x, d=1) -> str:
    return f"{x * 100:.{d}f}%"


def _yi(x):
    if x is None:
        return "-"
    if x >= 1e8:
        return f"{x / 1e8:.0f}亿"
    if x >= 1e4:
        return f"{x / 1e4:.0f}万"
    return str(x)


FACTOR_NAMES = {
    "momentum": "动量", "quality": "质量", "value": "估值", "fund_flow": "资金流",
    "size": "规模", "reversal": "反转", "industry_momentum": "行业动量",
    "scale": "规模", "liquidity": "流动性", "premium": "折溢价",
    "tracking_error": "跟踪误差", "expense": "管理费",
}
FACTOR_DESC = {
    "momentum": "近 20/60 日收益率，捕捉趋势延续。",
    "quality": "ROE 与负债率，偏好盈利质量高、杠杆低。",
    "value": "PE/PB/股息率综合，行业内中性化后选低估。",
    "fund_flow": "主力资金净流入，衡量资金偏好方向。",
    "size": "总市值对数，偏好小市值（规模溢价）。数据缺失时退化为中性。",
    "reversal": "近 5 日收益取反，捕捉短期反转（跌多反弹）。",
    "industry_momentum": "行业内 60 日收益均值，捕捉行业轮动 β。",
    "scale": "ETF 规模（AUM），偏好规模大、不易清盘。",
    "liquidity": "成交额，偏好流动性好、冲击成本低。",
    "premium": "折溢价率，偏好贴近净值（溢价容忍 ±1%）。",
    "tracking_error": "净值相对标的指数偏差，越低越紧密。",
    "expense": "管理费（如有），越低越省。",
}


def build_strategy(cfg: dict) -> dict:
    """从 config.json 抽取可读的'策略画像'，供页面与 API 展示。"""
    models = cfg.get("models", {})
    risk = cfg.get("risk", {})
    regime = cfg.get("regime", {})
    costs = cfg.get("costs", {})
    sel = cfg.get("selection", {})
    benchmark = cfg.get("benchmark", "000300")

    stock_weights = models.get("stock_weights", {})
    etf_weights = models.get("etf_weights", {})

    def factors(weights):
        return [{
            "name": FACTOR_NAMES.get(k, k),
            "bar": round(v * 100),
            "weight": _pct(v, 0),
            "desc": FACTOR_DESC.get(k, ""),
        } for k, v in weights.items()]

    risk_rows = [
        {"k": "单标最大仓位", "v": _pct(risk.get("max_position_pct", 0), 0)},
        {"k": "止损线（默认）",
         "v": f'{_pct(risk.get("stop_loss_pct", 0), 0)}'
              f'（区间 {_pct(risk.get("min_stop_loss_pct", 0), 0)}'
              f'–{_pct(risk.get("max_stop_loss_pct", 0), 0)}）'},
        {"k": "相关性去重阈值",
         "v": f'{risk.get("max_correlation", 0)}（{"开启" if risk.get("dedup") else "关闭"}）'},
        {"k": "组合最大回撤阈值", "v": _pct(risk.get("max_drawdown_pct", 0), 0)},
        {"k": "每期候选总数", "v": str(risk.get("total_candidates", 0))},
    ]
    regime_rows = [
        {"k": "状态过滤", "v": "开启" if regime.get("enabled") else "关闭"},
        {"k": "参考指数",
         "v": f'沪深300（{regime.get("index")}）{regime.get("ma_window")}日均线之上满仓'},
        {"k": "risk_on 仓位缩放", "v": f'×{regime.get("risk_on_scale")}'},
        {"k": "risk_off 仓位缩放", "v": f'×{regime.get("risk_off_scale")}'},
    ]
    cost_rows = [
        {"k": "佣金", "v": _pct(costs.get("commission", 0), 3)},
        {"k": "滑点", "v": _pct(costs.get("slippage", 0), 3)},
        {"k": "双边成本", "v": _pct(costs.get("round_trip", 0), 3)},
    ]
    s = sel.get("stock", {})
    e = sel.get("etf", {})
    universe_rows = [
        {"k": "选股池",
         "v": f'Top {s.get("top_n")} / 扫描 {s.get("scan_count")} 只 / '
              f'最小市值 {_yi(s.get("min_market_cap"))} / '
              f'最小日成交额 {_yi(s.get("min_amount"))} / '
              f'单行业≤{s.get("max_per_industry")} / '
              f'行业内中性化：{"是" if sel.get("industry_neutral") else "否"}'},
        {"k": "ETF 池",
         "v": f'Top {e.get("top_n")} / 最小规模 {_yi(e.get("min_aum"))} / '
              f'最小日成交额 {_yi(e.get("min_amount"))}'},
    ]
    methodology = [
        "数据获取与缓存：按交易日从 AKShare 拉取行情/财务/资金流，写入 SQLite 缓存；失败则告警并中止推送。",
        "因子计算：股票算动量/质量/估值/资金流，ETF 算规模/流动性/折溢价/动量/跟踪误差。",
        "标准化与中性化：行业内做 Z-Score 标准化，剔除行业 β，仅保留个股 α。",
        "加权合成：按 config 权重合成 composite 分数，降序取 Top N。",
        "风控处理：相关性去重（阈值 0.7）+ 市场状态（沪深300 MA200）缩放仓位 + 个股止损。",
        "输出与留存：生成候选清单、因子贡献分解，并写入历史库供复盘。",
    ]

    return {
        "model": models.get("active_selection_model", "multi_factor_v1"),
        "benchmark": benchmark,
        "benchmark_name": "沪深300" if benchmark == "000300" else benchmark,
        "data_sources": "AKShare（行情/财务/资金流）+ SQLite 缓存",
        "stock_factors": factors(stock_weights),
        "etf_factors": factors(etf_weights),
        "risk_rows": risk_rows,
        "regime_rows": regime_rows,
        "cost_rows": cost_rows,
        "universe_rows": universe_rows,
        "methodology": methodology,
        "disclaimer": "本系统输出为量化研究信号，非买卖建议。市场有风险，投资需谨慎。",
    }
