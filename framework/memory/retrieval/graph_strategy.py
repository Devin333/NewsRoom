from __future__ import annotations

from framework.memory.models import MemoryQuery, MemorySearchResult


class GraphMemoryRetrievalStrategy:
    def search(self, query: MemoryQuery, *, store) -> list[MemorySearchResult]:
        relation_search = getattr(store, "relation_search", None)
        if callable(relation_search):
            return relation_search(query)
        return store.search(query)
