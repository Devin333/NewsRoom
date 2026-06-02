from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any


def field_value(value: Any, field_name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(field_name, default)
    if hasattr(value, field_name):
        return getattr(value, field_name)
    return default


def to_plain_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return deepcopy(dict(value))
    if hasattr(value, "to_dict"):
        result = value.to_dict()
        return deepcopy(result) if isinstance(result, dict) else {"value": result}
    if value is None:
        return {}
    return {"value": deepcopy(value)}


def list_value(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple | set):
        return list(value)
    return [value]


def string_list(value: Any) -> list[str]:
    result = []
    for item in list_value(value):
        if item is None:
            continue
        text = str(item)
        if text:
            result.append(text)
    return result


def float_value(value: Any, *, default: float | None) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


__all__ = [
    "field_value",
    "float_value",
    "list_value",
    "string_list",
    "to_plain_dict",
]
