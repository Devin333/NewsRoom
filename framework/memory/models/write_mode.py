from __future__ import annotations

from enum import Enum
from typing import Any


class MemoryWriteMode(str, Enum):
    APPEND = "append"
    UPSERT = "upsert"
    MERGE = "merge"
    PROMOTE = "promote"
    INVALIDATE = "invalidate"
    REPLACE = "replace"

    @classmethod
    def from_value(cls, value: Any) -> "MemoryWriteMode":
        if isinstance(value, cls):
            return value
        return cls(str(value))

    def mutates_existing(self) -> bool:
        return self in {
            MemoryWriteMode.UPSERT,
            MemoryWriteMode.MERGE,
            MemoryWriteMode.PROMOTE,
            MemoryWriteMode.INVALIDATE,
            MemoryWriteMode.REPLACE,
        }
