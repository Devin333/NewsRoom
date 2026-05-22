from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from framework.memory.indexing.document import MemoryDocument
from framework.memory.models import MemoryKind, MemoryScope, MemoryWriteRequest


@dataclass(frozen=True)
class MemoryIndexRequest:
    documents: list[MemoryDocument]
    kind: MemoryKind = MemoryKind.SEMANTIC
    scope: MemoryScope = MemoryScope.SESSION
    actor: str | None = None
    run_id: str | None = None
    namespace: str | None = None

    def to_write_request(self) -> MemoryWriteRequest:
        return MemoryWriteRequest(
            records=[document.to_record(kind=self.kind, scope=self.scope) for document in self.documents],
            actor=self.actor,
            run_id=self.run_id,
            namespace=self.namespace,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "documents": [document.to_dict() for document in self.documents],
            "kind": self.kind.value,
            "scope": self.scope.value,
            "actor": self.actor,
            "run_id": self.run_id,
            "namespace": self.namespace,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MemoryIndexRequest":
        return cls(
            documents=[MemoryDocument.from_dict(item) for item in payload.get("documents") or []],
            kind=MemoryKind.from_value(payload.get("kind") or MemoryKind.SEMANTIC),
            scope=MemoryScope.from_value(payload.get("scope") or MemoryScope.SESSION),
            actor=payload.get("actor"),
            run_id=payload.get("run_id"),
            namespace=payload.get("namespace"),
        )
