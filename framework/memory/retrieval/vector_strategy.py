from __future__ import annotations

from framework.memory.models import MemoryQuery, MemorySearchResult


class VectorMemoryRetrievalStrategy:
    def search(self, query: MemoryQuery, *, store) -> list[MemorySearchResult]:
        vector_search = getattr(store, "vector_search", None)
        if callable(vector_search):
            return vector_search(query)
        return store.search(query)
