from __future__ import annotations

from typing import Any, cast

from framework.memory.models import MemoryQuery, MemorySearchResult


class GraphMemoryRetrievalStrategy:
    def search(self, query: MemoryQuery, *, store: Any) -> list[MemorySearchResult]:
        relation_search = getattr(store, "relation_search", None)
        if callable(relation_search):
            result = relation_search(query)
        else:
            result = store.search(query)
        return cast(list[MemorySearchResult], result)
