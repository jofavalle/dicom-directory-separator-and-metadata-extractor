from __future__ import annotations
import os
from typing import Dict, Any
import yaml


def load_config(path: str | None) -> Dict[str, Any]:
    if not path:
        return {"protocol_map": {}, "protocol_regex": []}
    if not os.path.exists(path):
        return {"protocol_map": {}, "protocol_regex": []}
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg.setdefault("protocol_map", {})
    cfg.setdefault("protocol_regex", [])
    return cfg


def normalize_protocol(name: str | None, cfg: Dict[str, Any]) -> str:
    if not name:
        return "NA"
    s = str(name).strip()
    # Exact map first
    mp = cfg.get("protocol_map", {}) or {}
    if s in mp:
        return str(mp[s])
    # Regex rules (list of {pattern: , replace: })
    import re
    for rule in cfg.get("protocol_regex", []) or []:
        pat = rule.get("pattern")
        rep = rule.get("replace", "")
        if not pat:
            continue
        if re.search(pat, s, flags=re.IGNORECASE):
            return re.sub(pat, rep, s, flags=re.IGNORECASE)
    return s
