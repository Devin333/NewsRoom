from __future__ import annotations

from typing import Any

from business.layers.memory.ingestion import MemoryIngestionService, MemoryIndexDocument
from framework.memory import MemoryRecord


class ReportMemoryBuilder:
    def report_documents(
        self,
        report: Any,
        *,
        run_id: str,
        report_id: str | None = None,
        topic: str | None = None,
    ) -> list[MemoryIndexDocument]:
        return MemoryIngestionService(_NullDocumentStore()).report_documents(
            report,
            run_id=run_id,
            report_id=report_id,
            topic=topic,
        )

    def report_memory_records(
        self,
        report: Any,
        *,
        run_id: str,
        report_id: str | None = None,
        topic: str | None = None,
    ) -> list[MemoryRecord]:
        return MemoryIngestionService(_NullDocumentStore()).report_memory_records(
            report,
            run_id=run_id,
            report_id=report_id,
            topic=topic,
        )


class _NullDocumentStore:
    def upsert_documents(self, docs: list[MemoryIndexDocument]) -> None:
        return None
