from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any, Protocol

from core.framework.memory.models import (
    MemoryQuery,
    MemoryRecord,
    MemorySearchResult,
    MemoryWriteResult,
)


class MemoryStore(Protocol):
    def write(self, record: MemoryRecord) -> MemoryWriteResult:
        ...

    def write_many(self, records: list[MemoryRecord]) -> MemoryWriteResult:
        ...

    def get(self, memory_id: str) -> MemoryRecord | None:
        ...

    def search(self, query: MemoryQuery) -> list[MemorySearchResult]:
        ...

    def update(self, memory_id: str, patch: dict[str, Any]) -> MemoryRecord:
        ...

    def delete(self, memory_id: str) -> None:
        ...


class InMemoryMemoryStore:
    def __init__(self, records: list[MemoryRecord] | None = None) -> None:
        self._records: dict[str, MemoryRecord] = {}
        if records:
            self.write_many(records)

    def write(self, record: MemoryRecord) -> MemoryWriteResult:
        return self.write_many([record])

    def write_many(self, records: list[MemoryRecord]) -> MemoryWriteResult:
        for record in records:
            self._records[record.memory_id] = record
        return MemoryWriteResult(
            accepted_count=len(records),
            written_count=len(records),
            memory_ids=[record.memory_id for record in records],
        )

    def get(self, memory_id: str) -> MemoryRecord | None:
        return self._records.get(memory_id)

    def search(self, query: MemoryQuery) -> list[MemorySearchResult]:
        results: list[MemorySearchResult] = []
        query_terms = _terms(query.query)
        for record in self._records.values():
            if not _record_matches_query(record, query):
                continue
            score = _score_record(record, query_terms)
            if query.min_score is not None and score < query.min_score:
                continue
            results.append(
                MemorySearchResult(
                    record=record,
                    score=score,
                    match_reasons=_match_reasons(record, query_terms),
                )
            )
        results.sort(key=lambda result: result.score, reverse=True)
        return results[: query.limit]

    def update(self, memory_id: str, patch: dict[str, Any]) -> MemoryRecord:
        record = self._records.get(memory_id)
        if record is None:
            raise KeyError(memory_id)
        updated = replace(
            record,
            summary=patch.get("summary", record.summary),
            content=str(patch.get("content", record.content)),
            metadata={**record.metadata, **dict(patch.get("metadata") or {})},
            refs={**record.refs, **dict(patch.get("refs") or {})},
            embedding=patch.get("embedding", record.embedding),
            updated_at=patch.get("updated_at") if isinstance(patch.get("updated_at"), datetime) else None,
        )
        self._records[memory_id] = updated
        return updated

    def delete(self, memory_id: str) -> None:
        self._records.pop(memory_id, None)


def _record_matches_query(record: MemoryRecord, query: MemoryQuery) -> bool:
    if query.scopes and record.scope not in query.scopes:
        return False
    if query.kinds and record.kind not in query.kinds:
        return False
    if query.time_window is not None:
        if query.time_window.start is not None and record.created_at < query.time_window.start:
            return False
        if query.time_window.end is not None and record.created_at > query.time_window.end:
            return False
    for key, value in query.filters.items():
        if key == "collection":
            continue
        actual = _record_filter_value(record, key)
        if actual != value:
            return False
    return True


def _record_filter_value(record: MemoryRecord, key: str) -> Any:
    if key == "memory_id":
        return record.memory_id
    if key == "scope":
        return record.scope.value
    if key == "kind":
        return record.kind.value
    if key in record.refs:
        return record.refs[key]
    if key in record.metadata:
        return record.metadata[key]
    return getattr(record, key, None)


def _score_record(record: MemoryRecord, query_terms: set[str]) -> float:
    searchable = " ".join(
        part
        for part in [
            record.summary or "",
            record.content,
            " ".join(record.tags),
        ]
        if part
    )
    record_terms = _terms(searchable)
    if not query_terms:
        return 0.0
    overlap = len(query_terms & record_terms)
    if overlap == 0:
        return 0.0
    return overlap / len(query_terms)


def _match_reasons(record: MemoryRecord, query_terms: set[str]) -> list[str]:
    record_terms = _terms(f"{record.summary or ''} {record.content} {' '.join(record.tags)}")
    if query_terms & record_terms:
        return ["text_match"]
    return []


def _terms(text: str) -> set[str]:
    normalized = "".join(ch.lower() if ch.isalnum() else " " for ch in str(text))
    return {part for part in normalized.split() if part}
