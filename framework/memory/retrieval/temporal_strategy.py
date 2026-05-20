from __future__ import annotations

from framework.memory.models import MemoryQuery, MemorySearchResult


class TemporalMemoryRetrievalStrategy:
    def search(self, query: MemoryQuery, *, store) -> list[MemorySearchResult]:
        return store.search(query)
