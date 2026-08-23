"""QMT（迅投 xtquant）下单脚本生成器。

QMT 在本地运行，通过 xtquant 连接 MiniQmt 客户端下达真实订单。本适配器只生成脚本，
默认不自动运行——用户填好 ACCOUNT_ID 后手动调用 main() 执行一次再平衡。

⚠️ 实盘有风险：脚本按 QuantPick 目标组合下单，未内置自动风控循环。
   首次使用请先用模拟账户/小资金验证，并确认 order_stock 参数顺序与本地 xtquant 版本一致。
"""
from __future__ import annotations

import json

from src.execution.common import norm_code, META_LINE


def generate(target: dict, account: str = "", path: str | None = None) -> str:
    normed = {norm_code(c, "qmt"): v for c, v in target["positions"].items()}
    meta = META_LINE.format(source=target.get("source"), regime=target.get("regime"),
                             scale=target.get("scale"))
    tpl = '''# -*- coding: utf-8 -*-
# [QuantPick 自动生成] QMT 下单脚本（本地运行，需开启 MiniQmt 客户端）。
# {meta}
# ⚠️ 默认不自动运行。请填好 ACCOUNT_ID，手动调用 main() 执行一次再平衡。
# ⚠️ 实盘有风险：本脚本仅按目标组合下单，未内置自动风控循环。
from xtquant.xttrader import XtTrader
from xtquant.xttype import StockAccount
from xtquant import xtconstant

TARGET = __TARGET__
ACCOUNT_ID = "YOUR_ACCOUNT_ID"  # <- 改成你的资金账号


def _get_total(xt, acc):
    asset = xt.query_stock_asset(acc)
    positions = xt.query_stock_positions(acc) or []
    return asset.cash + sum(p.market_value for p in positions)


def rebalance_once(xt, acc):
    """按目标组合再平衡一次（买入到目标市值）。"""
    total = _get_total(xt, acc)
    for code, info in TARGET.items():
        tick = xt.get_full_tick([code])
        price = tick.get(code, {}).get("lastPrice") if tick else None
        if not price:
            continue
        desired = total * info["weight"]
        vol = int(desired / price / 100) * 100  # A 股 100 股一手
        if vol <= 0:
            continue
        xt.order_stock(acc, code, xtconstant.STOCK_BUY, vol,
                       xtconstant.FIX_PRICE, price, "QuantPick", "")


def main():
    xt = XtTrader()
    if not xt.connect():
        raise RuntimeError("连接 MiniQmt 失败，请确认客户端已开启")
    acc = StockAccount(ACCOUNT_ID, "STOCK")
    xt.subscribe(acc)
    rebalance_once(xt, acc)
    xt.disconnect()


if __name__ == "__main__":
    main()
'''
    code = (tpl.replace("__TARGET__", json.dumps(normed, ensure_ascii=False, indent=4))
                .replace("{meta}", meta))
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(code)
    return code
