from __future__ import annotations

from framework.memory.models import MemoryQuery, MemorySearchResult
from framework.memory.stores import MemoryStore


class KeywordMemoryRetrievalStrategy:
    def search(self, query: MemoryQuery, *, store: MemoryStore) -> list[MemorySearchResult]:
        return store.search(query)
