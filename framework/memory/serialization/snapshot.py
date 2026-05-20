from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from framework.memory.models import MemoryRecord


@dataclass(frozen=True)
class MemorySnapshot:
    schema_version: str
    records: list[MemoryRecord]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "records": [record.to_dict() for record in self.records],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MemorySnapshot":
        return cls(
            schema_version=str(payload.get("schema_version") or "1"),
            records=[MemoryRecord.from_dict(item) for item in payload.get("records") or []],
            metadata=dict(payload.get("metadata") or {}),
        )


class MemorySnapshotStore:
    def save(self, snapshot: MemorySnapshot, path: str | Path) -> None:
        Path(path).write_text(json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self, path: str | Path) -> MemorySnapshot:
        return MemorySnapshot.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
