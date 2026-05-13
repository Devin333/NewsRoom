from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


class DataBufferPermissionError(PermissionError):
    """Raised when a scoped buffer access violates read/write permissions."""


@dataclass(frozen=True)
class DataBufferSnapshot:
    values: dict[str, Any]
    lineage: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self.values)

    def lineage_to_dict(self) -> dict[str, list[dict[str, Any]]]:
        return deepcopy(self.lineage)


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
        self._lineage: dict[str, list[dict[str, Any]]] = {}

    def read(self, key: str) -> Any:
        if key not in self._values:
            raise KeyError(f"buffer key does not exist: {key}")
        return deepcopy(self._values[key])

    def write(self, key: str, value: Any, lineage: dict[str, Any] | None = None) -> None:
        self._values[key] = deepcopy(value)
        if lineage is not None:
            self._lineage.setdefault(key, []).append(deepcopy(lineage))

    def exists(self, key: str) -> bool:
        return key in self._values

    def snapshot(self) -> DataBufferSnapshot:
        return DataBufferSnapshot(values=deepcopy(self._values), lineage=deepcopy(self._lineage))

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

    def lineage(self, key: str | None = None) -> dict[str, list[dict[str, Any]]] | list[dict[str, Any]]:
        if key is None:
            return deepcopy(self._lineage)
        return deepcopy(self._lineage.get(key, []))

    def redact(self, policy: dict[str, Any] | None = None) -> dict[str, Any]:
        policy = policy or {}
        redacted_keys = {str(key) for key in policy.get("redacted_keys", [])}
        replacement = str(policy.get("replacement", "[REDACTED]"))
        return {
            key: replacement if key in redacted_keys or _looks_sensitive_key(key) else deepcopy(value)
            for key, value in self._values.items()
        }


class ScopedDataBuffer:
    def __init__(self, buffer: DataBuffer, read_keys: list[str], write_keys: list[str]) -> None:
        self._buffer = buffer
        self._read_keys = set(read_keys)
        self._write_keys = set(write_keys)

    def read(self, key: str) -> Any:
        if key not in self._read_keys:
            raise DataBufferPermissionError(f"read key is not allowed: {key}")
        return self._buffer.read(key)

    def write(self, key: str, value: Any, lineage: dict[str, Any] | None = None) -> None:
        if key not in self._write_keys:
            raise DataBufferPermissionError(f"write key is not allowed: {key}")
        self._buffer.write(key, value, lineage=lineage)

    def exists(self, key: str) -> bool:
        if key not in self._read_keys and key not in self._write_keys:
            raise DataBufferPermissionError(f"key is not in scope: {key}")
        return self._buffer.exists(key)

    def list_allowed_reads(self) -> list[str]:
        return sorted(self._read_keys)

    def list_allowed_writes(self) -> list[str]:
        return sorted(self._write_keys)


def _looks_sensitive_key(key: str) -> bool:
    key_lower = key.casefold()
    return any(
        token in key_lower
        for token in (
            "api_key",
            "apikey",
            "authorization",
            "client_secret",
            "password",
            "secret",
            "token",
        )
    )
