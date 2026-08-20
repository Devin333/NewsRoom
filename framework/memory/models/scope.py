from __future__ import annotations

from enum import Enum
from typing import Any


class MemoryScope(str, Enum):
    WORKING = "working"
    SESSION = "session"
    AGENT = "agent"
    GRAPH = "graph"
    USER = "user"
    GLOBAL = "global"
    ORGANIZATION = "organization"
    PROJECT = "project"

    @classmethod
    def default(cls) -> "MemoryScope":
        return cls.SESSION

    @classmethod
    def from_value(cls, value: Any) -> "MemoryScope":
        if isinstance(value, cls):
            return value
        return cls(str(value))

    def is_persistent(self) -> bool:
        return self in {
            MemoryScope.USER,
            MemoryScope.GLOBAL,
            MemoryScope.ORGANIZATION,
            MemoryScope.PROJECT,
        }

    def is_runtime_local(self) -> bool:
        return self in {MemoryScope.WORKING, MemoryScope.SESSION}
