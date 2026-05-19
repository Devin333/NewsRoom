from __future__ import annotations

from typing import Any

from core.framework.memory import MemoryQuery, MemoryRuntime
from core.framework.tools.models import ToolDefinition
from core.framework.tools.registry import ToolRegistry


DEFAULT_MEMORY_COLLECTION = "report_sections"


def register_memory_tools(
    registry: ToolRegistry,
    *,
    vector_store: Any | None = None,
    default_collection: str = DEFAULT_MEMORY_COLLECTION,
    ingestion_service: Any | None = None,
    memory_runtime: MemoryRuntime | None = None,
) -> None:
    runtime = memory_runtime or _runtime_from_vector_store(
        vector_store,
        default_collection=default_collection,
    )
    if runtime is None:
        raise ValueError("memory_runtime or vector_store is required")
    registry.register(
        ToolDefinition(
            name="memory.recall",
            description="Recall relevant memory records and assemble a compact context block.",
            input_schema={
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "scopes": {"type": "array", "items": {"type": "string"}},
                    "kinds": {"type": "array", "items": {"type": "string"}},
                    "filters": {"type": "object"},
                    "collection": {"type": "string"},
                    "limit": {"type": "integer"},
                    "min_score": {"type": "number"},
                    "score_threshold": {"type": "number"},
                    "max_context_tokens": {"type": "integer"},
                },
                "additionalProperties": False,
            },
            side_effect="read_only",
            concurrency_safe=True,
            max_result_bytes=500_000,
        ),
        lambda args: _recall_memory(
            args,
            runtime=runtime,
            default_collection=default_collection,
        ),
    )
    registry.register(
        ToolDefinition(
            name="memory.search",
            description="Deprecated alias for memory.recall with legacy vector-search-shaped output.",
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
            metadata={"deprecated_alias_for": "memory.recall"},
        ),
        lambda args: _recall_memory(
            args,
            runtime=runtime,
            default_collection=default_collection,
            legacy_search_shape=True,
        ),
    )
    registry.register(
        ToolDefinition(
            name="memory.write",
            description="Write generic memory records through the framework memory runtime.",
            input_schema={
                "required": ["records"],
                "properties": {
                    "records": {
                        "type": "array",
                        "items": {"type": "object"},
                    },
                    "mode": {"type": "string"},
                    "actor": {"type": "string"},
                    "run_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
            side_effect="writes_external_state",
            concurrency_safe=False,
            max_result_bytes=100_000,
            metadata={"writes_memory_runtime": True},
        ),
        lambda args: _write_memory(args, runtime=runtime),
    )
    if ingestion_service is not None:
        registry.register(
            ToolDefinition(
                name="memory.index",
                description="Deprecated: index report or evidence payloads into vector memory.",
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
                metadata={
                    "deprecated": True,
                    "deprecated_replacement": "memory.write",
                    "writes_vector_memory": True,
                },
            ),
            lambda args: _index_memory(args, ingestion_service=ingestion_service),
        )


def _recall_memory(
    args: dict[str, Any],
    *,
    runtime: MemoryRuntime,
    default_collection: str,
    legacy_search_shape: bool = False,
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
    recall_filters = dict(filters)
    recall_filters.setdefault("collection", collection)
    limit = _limit(args.get("limit"))
    min_score = args.get("min_score", args.get("score_threshold"))
    recall = runtime.recall(
        MemoryQuery(
            query=query_text,
            scopes=[str(value) for value in args.get("scopes") or []],
            kinds=[str(value) for value in args.get("kinds") or []],
            filters=recall_filters,
            limit=limit,
            min_score=float(min_score) if min_score is not None else None,
            max_context_tokens=_optional_int(args.get("max_context_tokens")),
        )
    )
    if not legacy_search_shape:
        payload = recall.to_dict()
        payload["collection"] = collection
        return payload
    return {
        "collection": collection,
        "query": query_text,
        "filters": dict(filters),
        "limit": limit,
        "result_count": recall.result_count,
        "results": [_legacy_search_result(result.to_dict()) for result in recall.results],
        "context_block": recall.context_block.to_dict(),
    }


def _write_memory(args: dict[str, Any], *, runtime: MemoryRuntime) -> dict[str, Any]:
    records = args.get("records")
    if not isinstance(records, list):
        raise ValueError("records must be an array")
    result = runtime.write(
        {
            "records": records,
            "mode": args.get("mode") or "append",
            "actor": _optional_string(args.get("actor")),
            "run_id": _optional_string(args.get("run_id")),
        }
    )
    return result.to_dict()


def _index_memory(
    args: dict[str, Any],
    *,
    ingestion_service: Any,
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


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _runtime_from_vector_store(
    vector_store: Any | None,
    *,
    default_collection: str,
) -> MemoryRuntime | None:
    if vector_store is None:
        return None
    from storage.memory import VectorMemoryStoreAdapter

    return MemoryRuntime(
        VectorMemoryStoreAdapter(vector_store, collection=default_collection)
    )


def _legacy_search_result(result: dict[str, Any]) -> dict[str, Any]:
    record = result.get("record")
    record_payload = dict(record) if isinstance(record, dict) else {}
    metadata = dict(result.get("metadata") or {})
    payload = dict(metadata)
    payload.update(record_payload.get("refs") or {})
    payload.setdefault("document_id", result.get("document_id") or result.get("memory_id"))
    payload.setdefault("text", result.get("text") or result.get("content"))
    source_type = metadata.get("source_type") or result.get("kind")
    legacy = {
        "document_id": result.get("document_id") or result.get("memory_id"),
        "score": result.get("score"),
        "text": result.get("text") or result.get("content"),
        "source_type": source_type,
        "payload": payload,
        "refs": dict(result.get("refs") or {}),
    }
    for key in ("run_id", "report_id", "evidence_id", "source_item_id", "topic", "section_id"):
        value = result.get(key) or payload.get(key)
        if value is not None:
            legacy[key] = value
    return legacy
