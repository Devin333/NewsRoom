from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from storage.vector import VectorSearchQuery, VectorSearchResult, qdrant_store_from_env


DEFAULT_MEMORY_COLLECTION = "report_sections"


class VectorSearchStore(Protocol):
    def search(self, query: VectorSearchQuery) -> list[VectorSearchResult]: ...


@dataclass(frozen=True)
class MemorySearchResultSet:
    collection: str
    query: str
    filters: dict[str, Any]
    limit: int
    results: list[VectorSearchResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "collection": self.collection,
            "query": self.query,
            "filters": dict(self.filters),
            "limit": self.limit,
            "result_count": len(self.results),
            "results": [result.to_dict() for result in self.results],
        }


class MemoryApplicationService:
    def __init__(self, vector_store: VectorSearchStore | None = None) -> None:
        self.vector_store = vector_store or qdrant_store_from_env()

    def search(
        self,
        *,
        text: str,
        collection: str = DEFAULT_MEMORY_COLLECTION,
        limit: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> MemorySearchResultSet:
        query = VectorSearchQuery(
            collection=collection,
            text=text,
            limit=limit,
            filters=filters or {},
        )
        return MemorySearchResultSet(
            collection=collection,
            query=text,
            filters=filters or {},
            limit=limit,
            results=self.vector_store.search(query),
        )
