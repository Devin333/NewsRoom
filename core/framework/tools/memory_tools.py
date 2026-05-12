from __future__ import annotations

from typing import Any, Protocol

from core.framework.tools.models import ToolDefinition
from core.framework.tools.registry import ToolRegistry
from storage.memory import MemoryIngestionService
from storage.vector import VectorSearchQuery, VectorSearchResult


DEFAULT_MEMORY_COLLECTION = "report_sections"


class VectorSearchStore(Protocol):
    def search(self, query: VectorSearchQuery) -> list[VectorSearchResult]: ...


def register_memory_tools(
    registry: ToolRegistry,
    *,
    vector_store: VectorSearchStore,
    default_collection: str = DEFAULT_MEMORY_COLLECTION,
    ingestion_service: MemoryIngestionService | None = None,
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
    if ingestion_service is not None:
        registry.register(
            ToolDefinition(
                name="memory.index",
                description="Index report or evidence payloads into vector memory.",
                input_schema={
                    "required": ["run_id"],
                    "properties": {
                        "run_id": {"type": "string"},
                        "report": {"type": "object"},
                        "evidence_bundle": {"type": "object"},
                        "run_output": {"type": "object"},
                        "report_id": {"type": "string"},
                        "topic": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                side_effect="writes_external_state",
                concurrency_safe=False,
                max_result_bytes=100_000,
                metadata={"writes_vector_memory": True},
            ),
            lambda args: _index_memory(args, ingestion_service=ingestion_service),
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


def _index_memory(
    args: dict[str, Any],
    *,
    ingestion_service: MemoryIngestionService,
) -> dict[str, Any]:
    run_id = str(args["run_id"]).strip()
    if not run_id:
        raise ValueError("run_id is required")

    output: dict[str, Any] = {}
    indexed_inputs: list[str] = []
    if args.get("run_output") is not None:
        run_output = args["run_output"]
        if not isinstance(run_output, dict):
            raise ValueError("run_output must be an object")
        output.update(run_output)
        indexed_inputs.append("run_output")
    if args.get("report") is not None:
        output["final_report"] = args["report"]
        indexed_inputs.append("report")
    if args.get("evidence_bundle") is not None:
        output["evidence_bundle"] = args["evidence_bundle"]
        indexed_inputs.append("evidence_bundle")

    if "final_report" not in output and "evidence_bundle" not in output:
        raise ValueError("report, evidence_bundle, or run_output is required")

    result = ingestion_service.ingest_run_output(
        output,
        run_id=run_id,
        report_id=_optional_string(args.get("report_id")),
        topic=_optional_string(args.get("topic")),
    )
    return {
        "run_id": run_id,
        "report_id": _optional_string(args.get("report_id")),
        "topic": _optional_string(args.get("topic")),
        "indexed_inputs": indexed_inputs,
        **result.to_dict(),
    }


def _limit(value: Any) -> int:
    if value is None:
        return 5
    return max(1, min(int(value), 100))


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
