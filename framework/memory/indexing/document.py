from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.memory.models import MemoryKind, MemoryRecord, MemoryReference, MemoryScope


@dataclass(frozen=True)
class MemoryDocument:
    document_id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    refs: list[MemoryReference] = field(default_factory=list)

    def to_record(self, *, kind: MemoryKind = MemoryKind.SEMANTIC, scope: MemoryScope = MemoryScope.SESSION) -> MemoryRecord:
        return MemoryRecord(
            memory_id=self.document_id,
            content=self.text,
            kind=kind,
            scope=scope,
            metadata=self.metadata,
            refs=self.refs,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "text": self.text,
            "metadata": dict(self.metadata),
            "refs": [ref.to_dict() for ref in self.refs],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MemoryDocument":
        return cls(
            document_id=str(payload.get("document_id") or payload.get("id") or ""),
            text=str(payload.get("text") or ""),
            metadata=dict(payload.get("metadata") or {}),
            refs=[MemoryReference.from_dict(item) for item in payload.get("refs") or []],
        )
