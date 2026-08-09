"""推送层：飞书 / 企业微信 webhook 文本推送。"""
from __future__ import annotations

import requests
from src.config import get


def build_report(stock_df: pd.DataFrame, etf_df: pd.DataFrame) -> str:
    lines = ["📊 QuantPick 每日精选（仅供参考，非投资建议）"]
    if stock_df is not None and not stock_df.empty:
        lines.append("\n【股票 Top】")
        for _, r in stock_df.iterrows():
            pos = float(r.get("position_pct", 0) or 0) * 100
            lines.append(f"{int(r['rank'])}. {r.get('code')}  分数 {r['score']:.2f}  仓位 {pos:.1f}%")
    if etf_df is not None and not etf_df.empty:
        lines.append("\n【ETF Top】")
        for _, r in etf_df.iterrows():
            pos = float(r.get("position_pct", 0) or 0) * 100
            lines.append(f"{int(r['rank'])}. {r.get('code')}  分数 {r['score']:.2f}  仓位 {pos:.1f}%")
    return "\n".join(lines)


def send_feishu(webhook: str, text: str) -> bool:
    if not webhook:
        return False
    try:
        resp = requests.post(webhook, json={"msg_type": "text", "content": {"text": text}},
                             timeout=10)
        return resp.status_code == 200
    except Exception:
        return False


def send_wechat(webhook: str, text: str) -> bool:
    if not webhook:
        return False
    try:
        resp = requests.post(webhook, json={"msgtype": "text", "text": {"content": text}},
                             timeout=10)
        return resp.status_code == 200
    except Exception:
        return False


def notify(cfg: dict, text: str) -> None:
    local = get(cfg, "_local", default={}) or {}
    notif = local.get("notifications", {})
    if not notif.get("enabled"):
        return
    send_feishu(notif.get("feishu_webhook_url"), text)
    send_wechat(notif.get("wechat_webhook_url"), text)
