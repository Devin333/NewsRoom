from __future__ import annotations

from typing import Any, Protocol

from core.framework.tools.models import ToolDefinition
from core.framework.tools.registry import ToolRegistry
from storage.vector import VectorSearchQuery, VectorSearchResult


DEFAULT_MEMORY_COLLECTION = "report_sections"


class VectorSearchStore(Protocol):
    def search(self, query: VectorSearchQuery) -> list[VectorSearchResult]: ...


def register_memory_tools(
    registry: ToolRegistry,
    *,
    vector_store: VectorSearchStore,
    default_collection: str = DEFAULT_MEMORY_COLLECTION,
) -> None:
    registry.register(
        ToolDefinition(
            name="memory.search",
            description="Search vector memory for relevant report or evidence context.",
            input_schema={
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "collection": {"type": "string"},
                    "limit": {"type": "integer"},
                    "filters": {"type": "object"},
                    "score_threshold": {"type": "number"},
                },
                "additionalProperties": False,
            },
            side_effect="read_only",
            concurrency_safe=True,
            max_result_bytes=500_000,
        ),
        lambda args: _search_memory(
            args,
            vector_store=vector_store,
            default_collection=default_collection,
        ),
    )


def _search_memory(
    args: dict[str, Any],
    *,
    vector_store: VectorSearchStore,
    default_collection: str,
) -> dict[str, Any]:
    query_text = str(args["query"]).strip()
    if not query_text:
        raise ValueError("query is required")
    collection = str(args.get("collection") or default_collection).strip()
    if not collection:
        raise ValueError("collection is required")
    filters = args.get("filters") or {}
    if not isinstance(filters, dict):
        raise ValueError("filters must be an object")
    limit = _limit(args.get("limit"))
    score_threshold = args.get("score_threshold")
    vector_query = VectorSearchQuery(
        collection=collection,
        text=query_text,
        filters=dict(filters),
        limit=limit,
        score_threshold=float(score_threshold) if score_threshold is not None else None,
    )
    results = vector_store.search(vector_query)
    return {
        "collection": collection,
        "query": query_text,
        "filters": dict(filters),
        "limit": limit,
        "result_count": len(results),
        "results": [result.to_dict() for result in results],
    }


def _limit(value: Any) -> int:
    if value is None:
        return 5
    return max(1, min(int(value), 100))
