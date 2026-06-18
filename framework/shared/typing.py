from __future__ import annotations

from typing import Any

JsonValue = str | int | float | bool | None | dict[str, Any] | list[Any]
JsonDict = dict[str, Any]
Metadata = dict[str, Any]


def ensure_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError("value must be a dict")
    return dict(value)


def ensure_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError("value must be a list")
    return list(value)


def optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
