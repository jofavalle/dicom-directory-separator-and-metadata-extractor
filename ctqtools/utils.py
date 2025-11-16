import os
import json
import re
from typing import Any


def sanitize(text: str, keep: str = "-_. ") -> str:
    if text is None:
        return "NA"
    t = str(text)
    t = t.strip()
    t = re.sub(r"[\s]+", " ", t)
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" + keep)
    return "".join(ch if ch in allowed else "_" for ch in t)


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def to_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        try:
            return str(value)
        except Exception:
            return ""
