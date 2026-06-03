from __future__ import annotations

from typing import Any

from framework.workflow import DataBufferReadPermissionError, StepScopedDataBufferView
from business.boards.cross_board.workflows.daily_intelligence.buffer_key_aliases import (
    namespaced_first_key_candidates,
)


def read_buffer_value(
    buffer: StepScopedDataBufferView,
    key: str,
    *,
    required: bool = True,
    default: Any = None,
) -> Any:
    first_allowed_missing_key: str | None = None
    for candidate_key in _read_key_candidates(key):
        try:
            if buffer.exists(candidate_key):
                return buffer.read(candidate_key, required=required, default=default)
            first_allowed_missing_key = first_allowed_missing_key or candidate_key
        except DataBufferReadPermissionError:
            continue

    if not required:
        return default
    if first_allowed_missing_key is not None:
        return buffer.read(first_allowed_missing_key, required=True, default=default)
    return buffer.read(key, required=True, default=default)


def read_optional_buffer_value(
    buffer: StepScopedDataBufferView,
    key: str,
    *,
    default: Any = None,
) -> Any:
    return read_buffer_value(buffer, key, required=False, default=default)


def read_optional_buffer_dict(
    buffer: StepScopedDataBufferView,
    key: str,
) -> dict[str, Any] | None:
    value = read_optional_buffer_value(buffer, key)
    return dict(value) if isinstance(value, dict) else None


def read_buffer_list(buffer: StepScopedDataBufferView, key: str) -> list[Any]:
    value = read_buffer_value(buffer, key)
    if value is None:
        return []
    if isinstance(value, list | tuple):
        return list(value)
    raise TypeError(f"workflow buffer key {key!r} must contain a list or tuple")


def read_optional_buffer_list(buffer: StepScopedDataBufferView, key: str) -> list[Any]:
    value = read_optional_buffer_value(buffer, key)
    if value is None:
        return []
    if isinstance(value, list | tuple):
        return list(value)
    raise TypeError(f"workflow buffer key {key!r} must contain a list or tuple")


def append_buffer_items(buffer: StepScopedDataBufferView, key: str, *items: Any) -> list[Any]:
    values = read_buffer_list(buffer, key)
    values.extend(items)
    return values


def _read_key_candidates(key: str) -> list[str]:
    return namespaced_first_key_candidates(key)
