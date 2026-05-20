from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MemoryIndexResult:
    documents_received: int
    records_written: int
    memory_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "documents_received": self.documents_received,
            "records_written": self.records_written,
            "memory_ids": list(self.memory_ids),
            "errors": list(self.errors),
        }
