from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.tool.models.definition import ToolDefinition
from framework.tool.registry.registry import ToolRegistry


DEFAULT_MEMORY_COLLECTION = "memories"


def register_memory_tools(
    registry: ToolRegistry,
    *,
    vector_store: Any | None = None,
    default_collection: str = DEFAULT_MEMORY_COLLECTION,
    memory_runtime: Any | None = None,
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
        lambda args: _recall_memory(args, runtime=runtime, default_collection=default_collection),
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
                    "records": {"type": "array", "items": {"type": "object"}},
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
    registry.register(
        ToolDefinition(
            name="memory.explain",
            description="Describe the configured framework memory runtime and policy state.",
            input_schema={"properties": {}, "additionalProperties": False},
            side_effect="read_only",
            concurrency_safe=True,
            max_result_bytes=100_000,
        ),
        lambda args: _explain_memory_runtime(args, runtime=runtime),
    )
    registry.register(
        ToolDefinition(
            name="memory.consolidate",
            description="Consolidate matching memory records through the framework memory runtime.",
            input_schema={
                "properties": {
                    "memory_ids": {"type": "array", "items": {"type": "string"}},
                    "query": {"type": "object"},
                    "filters": {"type": "object"},
                    "actor": {"type": "string"},
                    "run_id": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "additionalProperties": False,
            },
            side_effect="writes_external_state",
            concurrency_safe=False,
            max_result_bytes=100_000,
            metadata={"writes_memory_runtime": True},
        ),
        lambda args: _consolidate_memory(args, runtime=runtime),
    )
    registry.register(
        ToolDefinition(
            name="memory.forget",
            description="Forget matching memory records through the framework memory runtime.",
            input_schema={
                "properties": {
                    "memory_id": {"type": "string"},
                    "memory_ids": {"type": "array", "items": {"type": "string"}},
                    "filters": {"type": "object"},
                    "actor": {"type": "string"},
                    "run_id": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "additionalProperties": False,
            },
            side_effect="writes_external_state",
            concurrency_safe=False,
            max_result_bytes=100_000,
            metadata={"writes_memory_runtime": True},
        ),
        lambda args: _forget_memory(args, runtime=runtime),
    )


def _recall_memory(
    args: dict[str, Any],
    *,
    runtime: Any,
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
        {
            "query": query_text,
            "scopes": [str(value) for value in args.get("scopes") or []],
            "kinds": [str(value) for value in args.get("kinds") or []],
            "filters": recall_filters,
            "limit": limit,
            "min_score": float(min_score) if min_score is not None else None,
            "max_context_tokens": _optional_int(args.get("max_context_tokens")),
        }
    )
    if not legacy_search_shape:
        payload = _to_dict(recall)
        payload["collection"] = collection
        return payload
    results = getattr(recall, "results", [])
    context_block = getattr(recall, "context_block", _MemoryContextBlock.empty())
    return {
        "collection": collection,
        "query": query_text,
        "filters": dict(filters),
        "limit": limit,
        "result_count": getattr(recall, "result_count", len(results)),
        "results": [_legacy_search_result(_to_dict(result)) for result in results],
        "context_block": _to_dict(context_block),
    }


def _write_memory(args: dict[str, Any], *, runtime: Any) -> dict[str, Any]:
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
    return _to_dict(result)


def _explain_memory_runtime(args: dict[str, Any], *, runtime: Any) -> dict[str, Any]:
    if args:
        raise ValueError("memory.explain does not accept arguments")
    return {
        "runtime_type": type(runtime).__name__,
        "store_type": type(getattr(runtime, "store", runtime)).__name__,
        "policy_type": type(getattr(runtime, "policy", None)).__name__ if getattr(runtime, "policy", None) is not None else None,
        "operations": {
            "recall": callable(getattr(runtime, "recall", None)),
            "write": callable(getattr(runtime, "write", None)),
            "get": callable(getattr(runtime, "get", None)),
            "consolidate": callable(getattr(runtime, "consolidate", None)),
            "forget": callable(getattr(runtime, "forget", None)),
        },
        "tools": {
            "memory.recall": "available",
            "memory.write": "available",
            "memory.search": "deprecated alias for memory.recall",
            "memory.explain": "available",
            "memory.consolidate": "available",
            "memory.forget": "available",
        },
    }


def _consolidate_memory(args: dict[str, Any], *, runtime: Any) -> dict[str, Any]:
    result = runtime.consolidate(dict(args))
    return _to_dict(result)


def _forget_memory(args: dict[str, Any], *, runtime: Any) -> dict[str, Any]:
    result = runtime.forget(dict(args))
    if result is None:
        memory_ids = _memory_ids_from_forget_args(args)
        return {"success": True, "forgotten_count": 0, "memory_ids": memory_ids}
    return _to_dict(result)


def _runtime_from_vector_store(vector_store: Any | None, *, default_collection: str) -> Any | None:
    if vector_store is None:
        return None
    return _VectorMemoryRuntime(vector_store, default_collection=default_collection)


@dataclass(frozen=True)
class _VectorSearchQuery:
    collection: str
    text: str
    vector: list[float] | None = None
    filters: dict[str, Any] = field(default_factory=dict)
    limit: int = 10
    score_threshold: float | None = None


@dataclass(frozen=True)
class _MemoryContextBlock:
    content: str
    token_estimate: int
    memory_ids: list[str] = field(default_factory=list)

    @classmethod
    def empty(cls) -> "_MemoryContextBlock":
        return cls(content="", token_estimate=0, memory_ids=[])

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "token_estimate": self.token_estimate,
            "memory_ids": list(self.memory_ids),
        }


@dataclass(frozen=True)
class _VectorRecallResult:
    query: dict[str, Any]
    results: list[Any]
    context_block: _MemoryContextBlock
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def result_count(self) -> int:
        return len(self.results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query.get("query") or "",
            "scopes": list(self.query.get("scopes") or []),
            "kinds": list(self.query.get("kinds") or []),
            "filters": dict(self.query.get("filters") or {}),
            "limit": int(self.query.get("limit") or 10),
            "result_count": self.result_count,
            "results": [_to_dict(result) for result in self.results],
            "context_block": self.context_block.to_dict(),
            "diagnostics": dict(self.diagnostics),
        }


class _VectorMemoryRuntime:
    def __init__(self, vector_store: Any, *, default_collection: str) -> None:
        self.store = vector_store
        self.default_collection = default_collection

    def recall(self, query: dict[str, Any] | str) -> _VectorRecallResult:
        if isinstance(query, str):
            query = {"query": query}
        filters = dict(query.get("filters") or {})
        collection = str(filters.pop("collection", self.default_collection))
        search_query = _VectorSearchQuery(
            collection=collection,
            text=str(query.get("query") or ""),
            filters=filters,
            limit=_limit(query.get("limit")),
            score_threshold=query.get("min_score"),
        )
        results = self.store.search(search_query)
        memory_ids = [
            str(getattr(result, "document_id", _to_dict(result).get("document_id", "")))
            for result in results
        ]
        context = "\n".join(str(_to_dict(result).get("text") or "") for result in results)
        return _VectorRecallResult(
            query={**dict(query), "filters": {"collection": collection, **filters}},
            results=list(results),
            context_block=_MemoryContextBlock(
                content=context,
                token_estimate=len(context.split()),
                memory_ids=[memory_id for memory_id in memory_ids if memory_id],
            ),
        )

    def write(self, request: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("vector-store memory adapter does not support memory.write")

    def consolidate(self, request: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("vector-store memory adapter does not support memory.consolidate")

    def forget(self, request: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("vector-store memory adapter does not support memory.forget")


def _legacy_search_result(result: dict[str, Any]) -> dict[str, Any]:
    record = result.get("record")
    record_payload = dict(record) if isinstance(record, dict) else {}
    metadata = dict(result.get("metadata") or {})
    payload = dict(metadata)
    payload.update(record_payload.get("refs") or {})
    payload.setdefault("document_id", result.get("document_id") or result.get("memory_id"))
    payload.setdefault("text", result.get("text") or result.get("content"))
    source_type = metadata.get("source_type") or result.get("source_type") or result.get("kind")
    legacy = {
        "document_id": result.get("document_id") or result.get("memory_id"),
        "score": result.get("score"),
        "text": result.get("text") or result.get("content"),
        "source_type": source_type,
        "payload": payload,
        "refs": dict(result.get("refs") or {}),
    }
    for key, value in legacy["refs"].items():
        if value is not None:
            legacy.setdefault(str(key), value)
    for key in ("run_id", "artifact_id", "record_id", "topic", "section_id"):
        value = result.get(key) or payload.get(key)
        if value is not None:
            legacy[key] = value
    return legacy


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


def _memory_ids_from_forget_args(args: dict[str, Any]) -> list[str]:
    memory_ids = [str(value) for value in args.get("memory_ids") or []]
    memory_id = _optional_string(args.get("memory_id"))
    if memory_id is not None:
        memory_ids.insert(0, memory_id)
    return memory_ids


def _to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    return dict(getattr(value, "__dict__", {}) or {})
