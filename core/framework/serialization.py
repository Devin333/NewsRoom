from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


def to_json_safe(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, Path):
        return value.as_posix()
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return to_json_safe(to_dict())
    if is_dataclass(value):
        return to_json_safe(asdict(value))
    if isinstance(value, dict):
        return {_json_key(key): to_json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [to_json_safe(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [to_json_safe(item) for item in sorted(value, key=repr)]
    return value


def _json_key(key: Any) -> str:
    if isinstance(key, Enum):
        return str(key.value)
    if isinstance(key, datetime):
        return key.isoformat().replace("+00:00", "Z")
    if isinstance(key, Path):
        return key.as_posix()
    return str(key)
