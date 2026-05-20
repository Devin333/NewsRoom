from __future__ import annotations

from typing import Any

from business.layers.memory.ingestion import MemoryIngestionService, MemoryIndexDocument
from framework.memory import MemoryRecord


class EvidenceMemoryBuilder:
    def evidence_documents(
        self,
        bundle: Any,
        *,
        run_id: str,
        topic: str | None = None,
    ) -> list[MemoryIndexDocument]:
        return MemoryIngestionService(_NullDocumentStore()).evidence_documents(
            bundle,
            run_id=run_id,
            topic=topic,
        )

    def evidence_memory_records(
        self,
        bundle: Any,
        *,
        run_id: str,
        topic: str | None = None,
    ) -> list[MemoryRecord]:
        return MemoryIngestionService(_NullDocumentStore()).evidence_memory_records(
            bundle,
            run_id=run_id,
            topic=topic,
        )


class _NullDocumentStore:
    def upsert_documents(self, docs: list[MemoryIndexDocument]) -> None:
        return None
