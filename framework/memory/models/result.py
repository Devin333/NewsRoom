from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.shared.redaction import redact_sensitive_values
from framework.memory.models.context import MemoryContextBlock
from framework.memory.models.query import MemoryQuery
from framework.memory.models.record import MemoryRecord, coerce_memory_record
from framework.memory.models.score import MemoryScore
from framework.memory.models.write_mode import MemoryWriteMode


@dataclass(frozen=True)
class MemoryOperationTrace:
    operation_id: str
    operation_type: str
    namespace: str | None = None
    query: str | None = None
    policy_decision: dict[str, Any] | None = None
    candidate_count: int = 0
    selected_count: int = 0
    filtered_count: int = 0
    scores: list[dict[str, Any]] = field(default_factory=list)
    duration_ms: float | None = None
    trace_id: str | None = None
    span_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation_id", str(self.operation_id))
        object.__setattr__(self, "operation_type", str(self.operation_type))
        object.__setattr__(
            self,
            "query",
            _optional_str(redact_sensitive_values(self.query)) if self.query is not None else None,
        )
        object.__setattr__(
            self,
            "policy_decision",
            (
                redact_sensitive_values(dict(self.policy_decision))
                if self.policy_decision is not None
                else None
            ),
        )
        object.__setattr__(self, "candidate_count", max(0, int(self.candidate_count or 0)))
        object.__setattr__(self, "selected_count", max(0, int(self.selected_count or 0)))
        object.__setattr__(self, "filtered_count", max(0, int(self.filtered_count or 0)))
        object.__setattr__(
            self,
            "scores",
            [
                redact_sensitive_values(dict(item))
                for item in self.scores
                if isinstance(item, dict)
            ],
        )
        object.__setattr__(
            self,
            "metadata",
            redact_sensitive_values(dict(self.metadata or {})),
        )

    @classmethod
    def from_any(cls, value: Any) -> "MemoryOperationTrace | None":
        if value is None:
            return None
        if isinstance(value, cls):
            return value
        if isinstance(value, dict):
            return cls(
                operation_id=str(value.get("operation_id") or ""),
                operation_type=str(value.get("operation_type") or ""),
                namespace=_optional_str(value.get("namespace")),
                query=_optional_str(value.get("query")),
                policy_decision=(
                    dict(value["policy_decision"])
                    if isinstance(value.get("policy_decision"), dict)
                    else None
                ),
                candidate_count=int(value.get("candidate_count") or 0),
                selected_count=int(value.get("selected_count") or 0),
                filtered_count=int(value.get("filtered_count") or 0),
                scores=[dict(item) for item in value.get("scores", []) if isinstance(item, dict)],
                duration_ms=_optional_float(value.get("duration_ms")),
                trace_id=_optional_str(value.get("trace_id")),
                span_id=_optional_str(value.get("span_id")),
                metadata=dict(value.get("metadata") or {}),
            )
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "operation_type": self.operation_type,
            "namespace": self.namespace,
            "query": self.query,
            "policy_decision": (
                dict(self.policy_decision) if self.policy_decision is not None else None
            ),
            "candidate_count": self.candidate_count,
            "selected_count": self.selected_count,
            "filtered_count": self.filtered_count,
            "scores": [dict(item) for item in self.scores],
            "duration_ms": self.duration_ms,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class MemorySearchResult:
    record: MemoryRecord
    score: float = 0.0
    source: str = "memory"
    match_reasons: list[str] = field(default_factory=list)
    score_detail: MemoryScore | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "record", coerce_memory_record(self.record))
        object.__setattr__(self, "score", float(self.score))
        if self.score_detail is None:
            object.__setattr__(self, "score_detail", MemoryScore(relevance=max(0.0, min(self.score, 1.0))))
        elif not isinstance(self.score_detail, MemoryScore):
            object.__setattr__(self, "score_detail", MemoryScore.from_dict(_dict_or_empty(self.score_detail)))

    @property
    def memory_id(self) -> str:
        return self.record.memory_id

    def to_dict(self) -> dict[str, Any]:
        refs = _dict_or_empty(self.record.refs)
        payload = {
            "memory_id": self.record.memory_id,
            "document_id": self.record.memory_id,
            "kind": self.record.kind.value,
            "scope": self.record.scope.value,
            "summary": self.record.summary,
            "content": self.record.content,
            "text": self.record.content,
            "score": self.score,
            "score_detail": self.score_detail.to_dict() if self.score_detail is not None else None,
            "source": self.source,
            "refs": refs,
            "metadata": dict(self.record.metadata),
            "embedding": list(self.record.embedding) if self.record.embedding is not None else None,
            "match_reasons": list(self.match_reasons),
        }
        for key in _GENERIC_REF_KEYS:
            value = refs.get(key) or self.record.metadata.get(key)
            if value is not None:
                payload[key] = value
        payload["record"] = self.record.to_dict()
        return payload

    @classmethod
    def from_record(cls, record: MemoryRecord, *, relevance: float = 0.0) -> "MemorySearchResult":
        return cls(record=record, score=relevance, score_detail=MemoryScore(relevance=relevance))


@dataclass(frozen=True)
class MemoryRecallResult:
    query: MemoryQuery
    results: list[MemorySearchResult] = field(default_factory=list)
    context_block: MemoryContextBlock = field(default_factory=MemoryContextBlock.empty)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    policy_decision: dict[str, Any] | None = None
    operation_trace: MemoryOperationTrace | dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    error_envelope: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation_trace", MemoryOperationTrace.from_any(self.operation_trace))
        object.__setattr__(self, "warnings", [str(item) for item in self.warnings])
        if self.error_envelope is not None:
            object.__setattr__(self, "error_envelope", dict(self.error_envelope))

    @property
    def result_count(self) -> int:
        return len(self.results)

    def to_dict(self) -> dict[str, Any]:
        query_payload = self.query.to_dict()
        operation_trace = MemoryOperationTrace.from_any(self.operation_trace)
        return {
            "query": self.query.query,
            "scopes": query_payload["scopes"],
            "kinds": query_payload["kinds"],
            "filters": query_payload["filters"],
            "limit": self.query.limit,
            "result_count": self.result_count,
            "results": [result.to_dict() for result in self.results],
            "context_block": self.context_block.to_dict(),
            "diagnostics": dict(self.diagnostics),
            "policy_decision": dict(self.policy_decision) if self.policy_decision is not None else None,
            "operation_trace": (
                operation_trace.to_dict() if operation_trace is not None else None
            ),
            "warnings": list(self.warnings),
            "error_envelope": (
                dict(self.error_envelope) if self.error_envelope is not None else None
            ),
        }

    def top_records(self, limit: int | None = None) -> list[MemoryRecord]:
        records = [result.record for result in self.results]
        return records if limit is None else records[:limit]


@dataclass(frozen=True)
class MemoryWriteRequest:
    records: list[MemoryRecord]
    mode: MemoryWriteMode = MemoryWriteMode.APPEND
    actor: str | None = None
    run_id: str | None = None
    namespace: str | None = None
    tenant_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", [coerce_memory_record(record) for record in self.records])
        object.__setattr__(self, "mode", MemoryWriteMode.from_value(self.mode))
        if not self.records:
            raise ValueError("memory write records are required")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MemoryWriteRequest":
        return cls(
            records=[coerce_memory_record(record) for record in payload.get("records") or []],
            mode=payload.get("mode") or MemoryWriteMode.APPEND,
            actor=_optional_str(payload.get("actor")),
            run_id=_optional_str(payload.get("run_id")),
            namespace=_optional_str(payload.get("namespace")),
            tenant_id=_optional_str(payload.get("tenant_id")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "records": [record.to_dict() for record in self.records],
            "mode": self.mode.value,
            "actor": self.actor,
            "run_id": self.run_id,
            "namespace": self.namespace,
            "tenant_id": self.tenant_id,
        }


@dataclass(frozen=True)
class MemoryWriteResult:
    accepted_count: int = 0
    written_count: int = 0
    memory_ids: list[str] = field(default_factory=list)
    skipped_count: int = 0
    errors: list[str] = field(default_factory=list)
    policy_decision: dict[str, Any] | None = None
    operation_trace: MemoryOperationTrace | dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    error_envelope: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation_trace", MemoryOperationTrace.from_any(self.operation_trace))
        object.__setattr__(self, "warnings", [str(item) for item in self.warnings])
        if self.error_envelope is None:
            object.__setattr__(self, "error_envelope", _memory_error_envelope(self.errors))
        else:
            object.__setattr__(self, "error_envelope", dict(self.error_envelope))

    @property
    def success(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        operation_trace = MemoryOperationTrace.from_any(self.operation_trace)
        return {
            "success": self.success,
            "accepted_count": self.accepted_count,
            "written_count": self.written_count,
            "memory_ids": list(self.memory_ids),
            "skipped_count": self.skipped_count,
            "errors": list(self.errors),
            "policy_decision": dict(self.policy_decision) if self.policy_decision is not None else None,
            "operation_trace": (
                operation_trace.to_dict() if operation_trace is not None else None
            ),
            "warnings": list(self.warnings),
            "error_envelope": (
                dict(self.error_envelope) if self.error_envelope is not None else None
            ),
        }


@dataclass(frozen=True)
class MemoryConsolidationRequest:
    memory_ids: list[str] = field(default_factory=list)
    query: MemoryQuery | None = None
    filters: dict[str, Any] = field(default_factory=dict)
    actor: str | None = None
    run_id: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        memory_ids = [str(memory_id).strip() for memory_id in self.memory_ids if str(memory_id).strip()]
        query = self.query
        if query is not None and not isinstance(query, MemoryQuery):
            query = MemoryQuery.from_dict(dict(query))
        filters = dict(self.filters or {})
        if not memory_ids and query is None and not filters:
            raise ValueError("memory_ids, query, or filters are required")
        object.__setattr__(self, "memory_ids", memory_ids)
        object.__setattr__(self, "query", query)
        object.__setattr__(self, "filters", filters)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MemoryConsolidationRequest":
        raw_query = payload.get("query")
        query = MemoryQuery.from_dict(raw_query) if isinstance(raw_query, dict) else None
        return cls(
            memory_ids=[str(value) for value in payload.get("memory_ids") or []],
            query=query,
            filters=dict(payload.get("filters") or {}),
            actor=_optional_str(payload.get("actor")),
            run_id=_optional_str(payload.get("run_id")),
            reason=_optional_str(payload.get("reason")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_ids": list(self.memory_ids),
            "query": self.query.to_dict() if self.query is not None else None,
            "filters": dict(self.filters),
            "actor": self.actor,
            "run_id": self.run_id,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class MemoryConsolidationResult:
    consolidated_count: int = 0
    memory_ids: list[str] = field(default_factory=list)
    source_memory_ids: list[str] = field(default_factory=list)
    skipped_count: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return not self.warnings

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "consolidated_count": self.consolidated_count,
            "memory_ids": list(self.memory_ids),
            "source_memory_ids": list(self.source_memory_ids),
            "skipped_count": self.skipped_count,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class MemoryForgetRequest:
    memory_ids: list[str] = field(default_factory=list)
    filters: dict[str, Any] = field(default_factory=dict)
    actor: str | None = None
    run_id: str | None = None
    reason: str | None = None
    hard_delete: bool = True

    def __post_init__(self) -> None:
        memory_ids = [str(memory_id).strip() for memory_id in self.memory_ids if str(memory_id).strip()]
        filters = dict(self.filters or {})
        if not memory_ids and not filters:
            raise ValueError("memory_ids or filters are required")
        object.__setattr__(self, "memory_ids", memory_ids)
        object.__setattr__(self, "filters", filters)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MemoryForgetRequest":
        memory_id = _optional_str(payload.get("memory_id"))
        memory_ids = [str(value) for value in payload.get("memory_ids") or []]
        if memory_id is not None:
            memory_ids.insert(0, memory_id)
        return cls(
            memory_ids=memory_ids,
            filters=dict(payload.get("filters") or {}),
            actor=_optional_str(payload.get("actor")),
            run_id=_optional_str(payload.get("run_id")),
            reason=_optional_str(payload.get("reason")),
            hard_delete=bool(payload.get("hard_delete", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_ids": list(self.memory_ids),
            "filters": dict(self.filters),
            "actor": self.actor,
            "run_id": self.run_id,
            "reason": self.reason,
            "hard_delete": self.hard_delete,
        }


@dataclass(frozen=True)
class MemoryForgetResult:
    forgotten_count: int = 0
    memory_ids: list[str] = field(default_factory=list)
    skipped_count: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return not self.warnings

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "forgotten_count": self.forgotten_count,
            "memory_ids": list(self.memory_ids),
            "skipped_count": self.skipped_count,
            "warnings": list(self.warnings),
        }


_GENERIC_REF_KEYS = (
    "artifact_id",
    "record_id",
    "reference_id",
    "reference_ids",
    "run_id",
    "source_memory_ids",
    "step_id",
    "workflow_id",
)


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _memory_error_envelope(errors: list[str]) -> dict[str, Any] | None:
    if not errors:
        return None
    return {
        "error_code": "MemoryRuntimeError",
        "error_type": "MemoryRuntimeError",
        "message": "; ".join(str(error) for error in errors),
        "domain": "memory",
        "severity": "error",
        "retryable": False,
        "details": {"errors": list(errors)},
    }
