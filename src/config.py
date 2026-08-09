"""配置加载：合并公共 config.json 与私有 config.local.json。

私有配置（飞书 webhook、代理等）不入库，按需放置 config.local.json。
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict


DEFAULT_PATH = "config.json"
LOCAL_PATH = "config.local.json"


def load_config(base_dir: str = ".") -> Dict[str, Any]:
    cfg: Dict[str, Any] = {}
    pub = os.path.join(base_dir, DEFAULT_PATH)
    if os.path.exists(pub):
        with open(pub, "r", encoding="utf-8") as f:
            cfg = json.load(f)

    loc = os.path.join(base_dir, LOCAL_PATH)
    local: Dict[str, Any] = {}
    if os.path.exists(loc):
        with open(loc, "r", encoding="utf-8") as f:
            local = json.load(f)
    cfg["_local"] = local
    return cfg


def get(cfg: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    """安全取嵌套配置：get(cfg, 'models', 'stock_weights', default={})"""
    cur = cfg
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur
