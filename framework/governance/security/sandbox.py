from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SandboxPolicy:
    network: bool = False
    filesystem_write: bool = False
    subprocess: bool = False

    def allow_network(self) -> bool:
        return self.network

    def allow_filesystem_write(self) -> bool:
        return self.filesystem_write

    def allow_subprocess(self) -> bool:
        return self.subprocess


@dataclass(frozen=True)
class SandboxGuard:
    policy: SandboxPolicy = SandboxPolicy()

    def check(self, operation: Any) -> list[str]:
        kind = _operation_kind(operation)
        if kind in {"network", "http", "https"} and not self.policy.allow_network():
            return ["network access is not allowed"]
        if kind in {"filesystem_write", "file_write", "write"} and not self.policy.allow_filesystem_write():
            return ["filesystem writes are not allowed"]
        if kind in {"subprocess", "process", "shell"} and not self.policy.allow_subprocess():
            return ["subprocess execution is not allowed"]
        return []


def _operation_kind(operation: Any) -> str:
    if isinstance(operation, str):
        return operation
    if isinstance(operation, Mapping):
        return str(operation.get("kind") or operation.get("type") or operation.get("operation") or "")
    return str(
        getattr(operation, "kind", None)
        or getattr(operation, "type", None)
        or getattr(operation, "operation", None)
        or ""
    )
