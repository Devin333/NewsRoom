from __future__ import annotations

from typing import Any, cast

from framework.memory.models import MemoryQuery, MemorySearchResult


class VectorMemoryRetrievalStrategy:
    def search(self, query: MemoryQuery, *, store: Any) -> list[MemorySearchResult]:
        vector_search = getattr(store, "vector_search", None)
        if callable(vector_search):
            result = vector_search(query)
        else:
            result = store.search(query)
        return cast(list[MemorySearchResult], result)
