from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from framework.memory.models import MemoryQuery, MemoryRecord, MemorySearchResult, MemoryWriteResult


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


class VectorMemoryStore(Protocol):
    def vector_search(self, query: MemoryQuery) -> list[MemorySearchResult]:
        ...

    def upsert_vectors(self, records: list[MemoryRecord]) -> MemoryWriteResult:
        ...


class KeywordMemoryStore(Protocol):
    def keyword_search(self, query: MemoryQuery) -> list[MemorySearchResult]:
        ...


class GraphMemoryStore(Protocol):
    def relation_search(self, query: MemoryQuery) -> list[MemorySearchResult]:
        ...


class TemporalMemoryStore(Protocol):
    def search_at_time(self, query: MemoryQuery, at: datetime) -> list[MemorySearchResult]:
        ...


class HybridMemoryStore(MemoryStore, Protocol):
    pass
