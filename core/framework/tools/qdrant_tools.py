from __future__ import annotations

from typing import Any, Protocol

from core.framework.tools.models import ToolDefinition
from core.framework.tools.registry import ToolRegistry
from storage.vector import VectorSearchQuery, VectorSearchResult


class QdrantSearchStore(Protocol):
    def search(self, query: VectorSearchQuery) -> list[VectorSearchResult]: ...


def register_qdrant_tools(
    registry: ToolRegistry,
    *,
    vector_store: QdrantSearchStore,
) -> None:
    registry.register(
        ToolDefinition(
            name="qdrant.search",
            description="Search a Qdrant vector collection through the configured vector store.",
            input_schema={
                "required": ["collection"],
                "properties": {
                    "collection": {"type": "string"},
                    "query": {"type": "string"},
                    "vector": {"type": "array"},
                    "filters": {"type": "object"},
                    "limit": {"type": "integer"},
                    "score_threshold": {"type": "number"},
                },
                "additionalProperties": False,
            },
            side_effect="read_only",
            concurrency_safe=True,
            max_result_bytes=500_000,
            metadata={"storage_backend": "qdrant"},
        ),
        lambda args: _search_qdrant(args, vector_store=vector_store),
    )


def _search_qdrant(
    args: dict[str, Any],
    *,
    vector_store: QdrantSearchStore,
) -> dict[str, Any]:
    collection = str(args["collection"]).strip()
    if not collection:
        raise ValueError("collection is required")

    query_text = str(args.get("query") or "").strip()
    vector = _optional_vector(args.get("vector"))
    if not query_text and vector is None:
        raise ValueError("query or vector is required")

    filters = args.get("filters") or {}
    if not isinstance(filters, dict):
        raise ValueError("filters must be an object")

    limit = _limit(args.get("limit"))
    score_threshold = args.get("score_threshold")
    vector_query = VectorSearchQuery(
        collection=collection,
        text=query_text,
        vector=vector,
        filters=dict(filters),
        limit=limit,
        score_threshold=float(score_threshold) if score_threshold is not None else None,
    )
    results = vector_store.search(vector_query)
    return {
        "collection": collection,
        "query": query_text or None,
        "vector_dimensions": len(vector) if vector is not None else None,
        "filters": dict(filters),
        "limit": limit,
        "result_count": len(results),
        "results": [result.to_dict() for result in results],
    }


def _optional_vector(value: Any) -> list[float] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("vector must be an array")
    vector = [float(item) for item in value]
    if not vector:
        raise ValueError("vector must not be empty")
    return vector


def _limit(value: Any) -> int:
    if value is None:
        return 10
    return max(1, min(int(value), 100))
