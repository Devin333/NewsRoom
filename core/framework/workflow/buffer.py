from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any


class DataBufferPermissionError(PermissionError):
    """Raised when a scoped buffer access violates read/write permissions."""


@dataclass(frozen=True)
class DataBufferSnapshot:
    values: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self.values)


@dataclass(frozen=True)
class DataBufferDiff:
    added: dict[str, Any]
    changed: dict[str, dict[str, Any]]
    removed: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "added": deepcopy(self.added),
            "changed": deepcopy(self.changed),
            "removed": deepcopy(self.removed),
        }


class DataBuffer:
    def __init__(self, initial_values: dict[str, Any] | None = None) -> None:
        self._values: dict[str, Any] = deepcopy(initial_values or {})

    def read(self, key: str) -> Any:
        if key not in self._values:
            raise KeyError(f"buffer key does not exist: {key}")
        return deepcopy(self._values[key])

    def write(self, key: str, value: Any) -> None:
        self._values[key] = deepcopy(value)

    def exists(self, key: str) -> bool:
        return key in self._values

    def snapshot(self) -> DataBufferSnapshot:
        return DataBufferSnapshot(values=deepcopy(self._values))

    def diff(self, previous: DataBufferSnapshot) -> DataBufferDiff:
        previous_values = previous.to_dict()
        current_values = deepcopy(self._values)
        added = {
            key: value
            for key, value in current_values.items()
            if key not in previous_values
        }
        removed = {
            key: value
            for key, value in previous_values.items()
            if key not in current_values
        }
        changed = {
            key: {
                "previous": previous_values[key],
                "current": current_values[key],
            }
            for key in current_values.keys() & previous_values.keys()
            if current_values[key] != previous_values[key]
        }
        return DataBufferDiff(added=added, changed=changed, removed=removed)

    def scope(self, read_keys: list[str], write_keys: list[str]) -> ScopedDataBuffer:
        return ScopedDataBuffer(self, read_keys=read_keys, write_keys=write_keys)


class ScopedDataBuffer:
    def __init__(self, buffer: DataBuffer, read_keys: list[str], write_keys: list[str]) -> None:
        self._buffer = buffer
        self._read_keys = set(read_keys)
        self._write_keys = set(write_keys)

    def read(self, key: str) -> Any:
        if key not in self._read_keys:
            raise DataBufferPermissionError(f"read key is not allowed: {key}")
        return self._buffer.read(key)

    def write(self, key: str, value: Any) -> None:
        if key not in self._write_keys:
            raise DataBufferPermissionError(f"write key is not allowed: {key}")
        self._buffer.write(key, value)

    def exists(self, key: str) -> bool:
        if key not in self._read_keys and key not in self._write_keys:
            raise DataBufferPermissionError(f"key is not in scope: {key}")
        return self._buffer.exists(key)

    def list_allowed_reads(self) -> list[str]:
        return sorted(self._read_keys)

    def list_allowed_writes(self) -> list[str]:
        return sorted(self._write_keys)
