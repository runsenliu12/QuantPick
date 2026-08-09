"""推送层：飞书 / 企业微信 webhook 文本推送，以及失败/空结果告警。"""
from __future__ import annotations

import logging

import pandas as pd
import requests
from src.config import get

logger = logging.getLogger("quantpick.notify")


def build_report(stock_df: pd.DataFrame, etf_df: pd.DataFrame, regime: dict | None = None) -> str:
    lines = ["📊 QuantPick 每日精选（仅供参考，非投资建议）"]
    if regime:
        lines.append(f"市场状态：{regime.get('state')}（仓位缩放 {regime.get('scale')}）")
    if stock_df is not None and not stock_df.empty:
        lines.append("\n【股票 Top】")
        for _, r in stock_df.iterrows():
            pos = float(r.get("position_pct", 0) or 0) * 100
            sl = float(r.get("stop_loss_pct", 0) or 0) * 100
            name = r.get("name") or r.get("code")
            lines.append(f"{int(r['rank'])}. {name}({r.get('code')}) 分 {r['score']:.2f} 仓 {pos:.1f}% 止损 {sl:.1f}%")
    if etf_df is not None and not etf_df.empty:
        lines.append("\n【ETF Top】")
        for _, r in etf_df.iterrows():
            pos = float(r.get("position_pct", 0) or 0) * 100
            sl = float(r.get("stop_loss_pct", 0) or 0) * 100
            name = r.get("name") or r.get("code")
            lines.append(f"{int(r['rank'])}. {name}({r.get('code')}) 分 {r['score']:.2f} 仓 {pos:.1f}% 止损 {sl:.1f}%")
    if (stock_df is None or stock_df.empty) and (etf_df is None or etf_df.empty):
        lines.append("\n⚠️ 本期为空（数据未取到或市场过滤），请检查数据源。")
    return "\n".join(lines)


def send_feishu(webhook: str, text: str) -> bool:
    if not webhook:
        return False
    try:
        resp = requests.post(webhook, json={"msg_type": "text", "content": {"text": text}},
                             timeout=10)
        return resp.status_code == 200
    except Exception as e:
        logger.warning("飞书推送失败: %s", e)
        return False


def send_wechat(webhook: str, text: str) -> bool:
    if not webhook:
        return False
    try:
        resp = requests.post(webhook, json={"msgtype": "text", "text": {"content": text}},
                             timeout=10)
        return resp.status_code == 200
    except Exception as e:
        logger.warning("企微推送失败: %s", e)
        return False


def notify(cfg: dict, text: str) -> None:
    local = get(cfg, "_local", default={}) or {}
    notif = local.get("notifications", {})
    if not notif.get("enabled"):
        return
    send_feishu(notif.get("feishu_webhook_url"), text)
    send_wechat(notif.get("wechat_webhook_url"), text)


def alert(cfg: dict, reason: str) -> None:
    """异常/空结果告警（与 notify 同通道，但带 ⚠️ 前缀便于区分）。"""
    logger.warning("告警: %s", reason)
    notify(cfg, "⚠️ QuantPick 告警：\n" + reason)
