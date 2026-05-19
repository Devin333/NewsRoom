from __future__ import annotations

from typing import Any
from uuid import uuid4

from core.framework.memory.models import (
    MemoryConsolidationRequest,
    MemoryConsolidationResult,
    MemoryForgetRequest,
    MemoryForgetResult,
    MemoryKind,
    MemoryQuery,
    MemoryRecallResult,
    MemoryRecord,
    MemoryScope,
    MemoryWriteRequest,
    MemoryWriteResult,
    MemoryWriteMode,
)
from core.framework.memory.policy import DEFAULT_WORKFLOW_MEMORY_POLICY, MemoryPolicy
from core.framework.memory.recall import MemoryContextAssembler, MemoryRecallStrategy, SimpleMemoryRecallStrategy
from core.framework.memory.store import MemoryStore
from core.framework.memory.writer import MemoryWriter


class MemoryRuntime:
    def __init__(
        self,
        store: MemoryStore,
        *,
        policy: MemoryPolicy | None = None,
        recall_strategy: MemoryRecallStrategy | None = None,
        assembler: MemoryContextAssembler | None = None,
        writer: MemoryWriter | None = None,
    ) -> None:
        self.store = store
        self.policy = policy or DEFAULT_WORKFLOW_MEMORY_POLICY
        self.recall_strategy = recall_strategy or SimpleMemoryRecallStrategy()
        self.assembler = assembler or MemoryContextAssembler()
        self.writer = writer or MemoryWriter()

    def recall(
        self,
        query: MemoryQuery | dict[str, Any] | str,
        *,
        policy: MemoryPolicy | None = None,
    ) -> MemoryRecallResult:
        memory_query = _coerce_query(query)
        return self.recall_strategy.recall(
            memory_query,
            store=self.store,
            policy=policy or self.policy,
            assembler=self.assembler,
        )

    def write(
        self,
        request: MemoryWriteRequest | dict[str, Any] | None = None,
        *,
        records: list[MemoryRecord | dict[str, Any]] | None = None,
        mode: MemoryWriteMode | str = MemoryWriteMode.APPEND,
        actor: str | None = None,
        run_id: str | None = None,
        policy: MemoryPolicy | None = None,
    ) -> MemoryWriteResult:
        write_request = _coerce_write_request(
            request,
            records=records,
            mode=mode,
            actor=actor,
            run_id=run_id,
        )
        return self.writer.write(
            write_request,
            store=self.store,
            policy=policy or self.policy,
        )

    def get(self, memory_id: str) -> MemoryRecord | None:
        return self.store.get(memory_id)

    def forget(
        self,
        request: MemoryForgetRequest | dict[str, Any] | str,
    ) -> MemoryForgetResult:
        if isinstance(request, str):
            self.store.delete(request)
            return MemoryForgetResult(forgotten_count=1, memory_ids=[request])
        forget_request = _coerce_forget_request(request)
        memory_ids = _memory_ids_for_forget(forget_request, store=self.store)
        forgotten: list[str] = []
        warnings: list[str] = []
        for memory_id in memory_ids:
            try:
                self.store.delete(memory_id)
            except NotImplementedError as exc:
                warnings.append(str(exc))
                continue
            forgotten.append(memory_id)
        skipped_count = max(0, len(memory_ids) - len(forgotten))
        return MemoryForgetResult(
            forgotten_count=len(forgotten),
            memory_ids=forgotten,
            skipped_count=skipped_count,
            warnings=warnings,
        )

    def consolidate(
        self,
        request: MemoryConsolidationRequest | dict[str, Any],
    ) -> MemoryConsolidationResult:
        consolidation_request = _coerce_consolidation_request(request)
        source_records = _records_for_consolidation(consolidation_request, store=self.store)
        if not source_records:
            return MemoryConsolidationResult(
                consolidated_count=0,
                skipped_count=1,
                warnings=["no memories matched consolidation request"],
            )
        consolidated = _consolidated_record(consolidation_request, source_records)
        write = self.write(
            records=[consolidated],
            mode=MemoryWriteMode.UPSERT,
            actor=consolidation_request.actor,
            run_id=consolidation_request.run_id,
        )
        return MemoryConsolidationResult(
            consolidated_count=write.written_count,
            memory_ids=list(write.memory_ids),
            source_memory_ids=[record.memory_id for record in source_records],
            skipped_count=write.skipped_count,
            warnings=list(write.errors),
        )


def _coerce_query(value: MemoryQuery | dict[str, Any] | str) -> MemoryQuery:
    if isinstance(value, MemoryQuery):
        return value
    if isinstance(value, dict):
        return MemoryQuery.from_dict(value)
    return MemoryQuery(query=str(value))


def _coerce_write_request(
    request: MemoryWriteRequest | dict[str, Any] | None,
    *,
    records: list[MemoryRecord | dict[str, Any]] | None,
    mode: MemoryWriteMode | str,
    actor: str | None,
    run_id: str | None,
) -> MemoryWriteRequest:
    if isinstance(request, MemoryWriteRequest):
        return request
    if isinstance(request, dict):
        return MemoryWriteRequest.from_dict(request)
    return MemoryWriteRequest(
        records=list(records or []),
        mode=mode,
        actor=actor,
        run_id=run_id,
    )


def _coerce_forget_request(
    request: MemoryForgetRequest | dict[str, Any],
) -> MemoryForgetRequest:
    if isinstance(request, MemoryForgetRequest):
        return request
    return MemoryForgetRequest.from_dict(request)


def _coerce_consolidation_request(
    request: MemoryConsolidationRequest | dict[str, Any],
) -> MemoryConsolidationRequest:
    if isinstance(request, MemoryConsolidationRequest):
        return request
    return MemoryConsolidationRequest.from_dict(request)


def _memory_ids_for_forget(
    request: MemoryForgetRequest,
    *,
    store: MemoryStore,
) -> list[str]:
    memory_ids = list(dict.fromkeys(request.memory_ids))
    if request.filters:
        query = MemoryQuery(query="", filters=request.filters, limit=100)
        memory_ids.extend(result.memory_id for result in store.search(query))
    return list(dict.fromkeys(memory_ids))


def _records_for_consolidation(
    request: MemoryConsolidationRequest,
    *,
    store: MemoryStore,
) -> list[MemoryRecord]:
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


def _consolidated_record(
    request: MemoryConsolidationRequest,
    records: list[MemoryRecord],
) -> MemoryRecord:
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


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)
