from __future__ import annotations

from typing import Any

from framework.workflow import StepScopedDataBufferView


def read_buffer_list(buffer: StepScopedDataBufferView, key: str) -> list[Any]:
    value = buffer.read(key)
    if value is None:
        return []
    if isinstance(value, list | tuple):
        return list(value)
    raise TypeError(f"workflow buffer key {key!r} must contain a list or tuple")


def append_buffer_items(buffer: StepScopedDataBufferView, key: str, *items: Any) -> list[Any]:
    values = read_buffer_list(buffer, key)
    values.extend(items)
    return values
