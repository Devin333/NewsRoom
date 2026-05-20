from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MemoryRuntimeMetrics:
    total_records: int
    records_by_kind: dict[str, int]
    records_by_scope: dict[str, int]
    expired_records: int
    invalidated_records: int
    average_confidence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_records": self.total_records,
            "records_by_kind": dict(self.records_by_kind),
            "records_by_scope": dict(self.records_by_scope),
            "expired_records": self.expired_records,
            "invalidated_records": self.invalidated_records,
            "average_confidence": self.average_confidence,
        }
