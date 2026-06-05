from __future__ import annotations

from typing import Protocol

from framework.memory.models import MemoryQuery, MemoryRecord, MemorySearchResult, MemoryWriteResult


class VectorMemoryStore(Protocol):
    def vector_search(self, query: MemoryQuery) -> list[MemorySearchResult]:
        ...

    def upsert_vectors(self, records: list[MemoryRecord]) -> MemoryWriteResult:
        ...

__all__ = ["VectorMemoryStore"]
