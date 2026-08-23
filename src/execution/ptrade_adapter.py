"""PTrade（恒生）策略生成器。

PTrade 策略运行在券商服务器端，API 与聚宽/优矿类似：initialize / handle_data /
context.portfolio / order_target_value。生成的是"策略源码文件"，由用户上传到 PTrade
运行——本适配器只产出代码，绝不连接券商、绝不下单。

⚠️ 上传前请核对 PTrade 实际 API 名称（不同券商版本可能略有差异）。
"""
from __future__ import annotations

import json

from src.execution.common import norm_code, META_LINE


def generate(target: dict, account: str = "", path: str | None = None) -> str:
    normed = {norm_code(c, "ptrade"): v for c, v in target["positions"].items()}
    meta = META_LINE.format(source=target.get("source"), regime=target.get("regime"),
                             scale=target.get("scale"))
    tpl = '''# -*- coding: utf-8 -*-
# [QuantPick 自动生成] PTrade 策略文件（券商服务器端运行）。本文件请勿手改。
# {meta}
# 目标组合（weight 为仓位比例 0~1）：
TARGET = __TARGET__

def initialize(context):
    g.target = TARGET
    g.entry = {}  # code -> 建仓成本价

def handle_data(context, data):
    total = context.portfolio.total_value
    for code, info in g.target.items():
        pos = context.portfolio.positions.get(code)
        cur = pos.value if pos else 0.0
        desired = total * info["weight"]
        if desired != cur:
            order_target_value(code, desired)
        # 自适应止损
        if pos and g.entry.get(code) and data[code].close < g.entry[code] * (1 - info["stop_loss"]):
            order_target_value(code, 0.0)
    # 记录建仓成本
    for code, info in g.target.items():
        pos = context.portfolio.positions.get(code)
        if pos and pos.total_amount > 0 and code not in g.entry:
            g.entry[code] = pos.avg_cost
'''
    code = (tpl.replace("__TARGET__", json.dumps(normed, ensure_ascii=False, indent=4))
                .replace("{meta}", meta))
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(code)
    return code
