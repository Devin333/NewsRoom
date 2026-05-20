from __future__ import annotations

from dataclasses import replace
from typing import Any

from framework.memory.exceptions import MemoryNotFound
from framework.memory.models import MemoryQuery, MemoryRecord, MemorySearchResult, MemoryWriteResult


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
                    source="keyword",
                    match_reasons=_match_reasons(record, query_terms),
                )
            )
        results.sort(key=lambda result: result.score, reverse=True)
        return results[: query.limit]

    def update(self, memory_id: str, patch: dict[str, Any]) -> MemoryRecord:
        record = self._records.get(memory_id)
        if record is None:
            raise MemoryNotFound(memory_id)
        updated = replace(
            record,
            kind=patch.get("kind", record.kind),
            scope=patch.get("scope", record.scope),
            summary=patch.get("summary", record.summary),
            content=str(patch.get("content", record.content)),
            metadata={**record.metadata, **dict(patch.get("metadata") or {})},
            refs={**record.refs, **dict(patch.get("refs") or {})},
            tags=[str(tag) for tag in patch.get("tags", record.tags)],
            confidence=patch.get("confidence", record.confidence),
            importance=patch.get("importance", record.importance),
            score=patch.get("score", record.score),
            embedding=patch.get("embedding", record.embedding),
            actor=patch.get("actor", record.actor),
            namespace=patch.get("namespace", record.namespace),
            tenant_id=patch.get("tenant_id", record.tenant_id),
            updated_at=patch.get("updated_at", record.updated_at),
            expires_at=patch.get("expires_at", record.expires_at),
            invalidated_at=patch.get("invalidated_at", record.invalidated_at),
            invalidation_reason=patch.get("invalidation_reason", record.invalidation_reason),
            version=patch.get("version", record.version),
        )
        self._records[memory_id] = updated
        return updated

    def delete(self, memory_id: str) -> None:
        self._records.pop(memory_id, None)

    def delete_many(self, memory_ids: list[str]) -> list[str]:
        deleted: list[str] = []
        for memory_id in memory_ids:
            if memory_id in self._records:
                self.delete(memory_id)
                deleted.append(memory_id)
        return deleted

    def delete_by_query(self, query: MemoryQuery) -> list[str]:
        matches = [result.memory_id for result in self.search(query)]
        return self.delete_many(matches)

    def records(self) -> list[MemoryRecord]:
        return list(self._records.values())


def _record_matches_query(record: MemoryRecord, query: MemoryQuery) -> bool:
    if not query.include_invalidated and record.is_invalidated():
        return False
    if not query.include_expired and record.is_expired():
        return False
    if query.scopes and record.scope not in query.scopes:
        return False
    if query.kinds and record.kind not in query.kinds:
        return False
    if query.namespace is not None and record.namespace != query.namespace:
        return False
    if query.tenant_id is not None and record.tenant_id != query.tenant_id:
        return False
    if query.tags and not set(query.tags).issubset(set(record.tags)):
        return False
    if query.time_window is not None and not query.time_window.contains(record.created_at):
        return False
    return query.matches_metadata(record)


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
