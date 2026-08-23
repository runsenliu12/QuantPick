"""执行层：把 QuantPick 的选股/选基输出变成可执行的券商策略。

子模块：
- target:   候选 -> 目标组合（target_portfolio.json）
- paper:    纸面执行模拟器（不连券商）
- ptrade_adapter / qmt_adapter / joinquant_adapter: 生成三平台策略代码

默认只"生成代码 + 模拟"，绝不连接券商、绝不自动下单。实盘需用户显式提供凭证并确认。
"""
from src.execution.target import build_target, save_target, load_target
from src.execution.paper import simulate, fetch_prices_demo

__all__ = ["build_target", "save_target", "load_target", "simulate", "fetch_prices_demo"]
