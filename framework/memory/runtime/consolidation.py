from __future__ import annotations

from uuid import uuid4

from framework.memory.models import (
    MemoryConsolidationRequest,
    MemoryConsolidationResult,
    MemoryKind,
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
    MemoryWriteMode,
)
from framework.memory.policy import MemoryPolicy
from framework.memory.runtime.writer import MemoryWriter
from framework.memory.stores import MemoryStore


class MemoryConsolidator:
    def consolidate(
        self,
        request: MemoryConsolidationRequest,
        *,
        store: MemoryStore,
        policy: MemoryPolicy,
        writer: MemoryWriter,
    ) -> MemoryConsolidationResult:
        source_records = self._load_source_records(request, store)
        if not source_records:
            return MemoryConsolidationResult(
                consolidated_count=0,
                skipped_count=1,
                warnings=["no memories matched consolidation request"],
            )
        consolidated = self._build_consolidated_record(request, source_records)
        write = writer.write(
            _write_request([consolidated], actor=request.actor, run_id=request.run_id),
            store=store,
            policy=policy,
        )
        return MemoryConsolidationResult(
            consolidated_count=write.written_count,
            memory_ids=list(write.memory_ids),
            source_memory_ids=[record.memory_id for record in source_records],
            skipped_count=write.skipped_count,
            warnings=list(write.errors),
        )

    def _load_source_records(self, request: MemoryConsolidationRequest, store: MemoryStore) -> list[MemoryRecord]:
        records: list[MemoryRecord] = []
        for memory_id in request.memory_ids:
            record = store.get(memory_id)
            if record is not None:
                records.append(record)
        if request.query is not None:
            records.extend(result.record for result in store.search(request.query))
        if request.filters:
            records.extend(
                result.record
                for result in store.search(MemoryQuery(query="", filters=request.filters, limit=100))
            )
        unique: dict[str, MemoryRecord] = {}
        for record in records:
            unique[record.memory_id] = record
        return list(unique.values())

    def _build_consolidated_record(self, request: MemoryConsolidationRequest, records: list[MemoryRecord]) -> MemoryRecord:
        source_ids = [record.memory_id for record in records]
        first = records[0]
        summaries = [record.summary or record.content for record in records]
        content = "\n".join(f"- {summary}" for summary in summaries)
        confidence_values = [record.confidence for record in records if record.confidence is not None]
        importance_values = [record.importance for record in records if record.importance is not None]
        metadata = {
            "consolidated_from": source_ids,
            "source_count": len(source_ids),
        }
        if request.reason:
            metadata["reason"] = request.reason
        refs = {
            "source_memory_ids": source_ids,
        }
        if request.run_id:
            refs["run_id"] = request.run_id
        return MemoryRecord(
            memory_id=f"consolidated-{uuid4().hex}",
            content=content,
            summary=f"Consolidated memory from {len(source_ids)} records",
            kind=MemoryKind.SEMANTIC,
            scope=first.scope if isinstance(first.scope, MemoryScope) else MemoryScope.SESSION,
            metadata=metadata,
            refs=refs,
            tags=sorted({tag for record in records for tag in record.tags}),
            confidence=_average(confidence_values),
            importance=_average(importance_values),
            actor=request.actor,
        )


def _write_request(records, *, actor, run_id):
    from framework.memory.models import MemoryWriteRequest

    return MemoryWriteRequest(records=records, mode=MemoryWriteMode.UPSERT, actor=actor, run_id=run_id)


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)
