"""目标组合（execution target）：把 QuantPick 的选股/选基输出收敛成一份可执行的组合。

输入：server.get_candidates() 的结构 {stocks:[...], etfs:[...], regime:{state,scale}}
输出：target_portfolio.json 结构 {positions: {code: {weight, stop_loss, kind, ...}}}

注意：stock 与 etf 各自 portfolio_weights 求和到 1，直接拼接会得到 ~2 的总仓位。
这里把两者合并后整体归一化到 1.0 × regime.scale（现金缓冲由 scale<1 体现），
得到一份统一的"目标组合"。用户可直接手改生成的 target_portfolio.json 调整权重。
"""
from __future__ import annotations

import json
from datetime import datetime


def build_target(candidates: dict, source: str = "selection") -> dict:
    regime = candidates.get("regime", {}) or {}
    scale = float(regime.get("scale", 1.0) or 1.0)
    raw = {}
    for kind, key in (("stock", "stocks"), ("etf", "etfs")):
        for r in (candidates.get(key) or []):
            code = str(r.get("code") or "")
            if not code:
                continue
            w = r.get("position_pct")
            if w is None:
                continue
            w = float(w)
            if w <= 0:
                continue
            raw[code] = {
                "name": r.get("name") or code,
                "weight": w,
                "stop_loss": round(float(r.get("stop_loss_pct") or 0.1), 4),
                "kind": kind,
                "rank": int(r.get("rank") or 0),
                "score": (float(r["score"]) if r.get("score") is not None else None),
            }

    total = sum(v["weight"] for v in raw.values())
    positions = {}
    for code, v in raw.items():
        w = (v["weight"] / total) if total > 0 else 0.0
        w = round(w * scale, 4)
        if w <= 0:
            continue
        positions[code] = {**v, "weight": w}

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": source,
        "regime": regime.get("state", "risk_on"),
        "scale": scale,
        "positions": positions,
    }


def save_target(target: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(target, f, ensure_ascii=False, indent=2)


def load_target(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
