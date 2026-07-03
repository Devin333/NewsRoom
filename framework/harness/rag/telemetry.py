from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from framework.harness.rag.models import RAGSessionStatus, RetrievalOperation
from framework.shared.json import to_jsonable


TRACER_NAME = "newsroom.framework.harness.rag"

try:  # pragma: no cover - exercised only when optional dependency is installed
    from opentelemetry import trace as _otel_trace
    from opentelemetry.trace import Status as _OtelStatus
    from opentelemetry.trace import StatusCode as _OtelStatusCode
except Exception:  # pragma: no cover - default dev environment has no OTel dependency
    _otel_trace = None
    _OtelStatus = None
    _OtelStatusCode = None


class RAGTelemetry:
    """Optional OpenTelemetry bridge for bounded Harness RAG sessions."""

    def __init__(self, tracer: Any | None = None) -> None:
        self._tracer = tracer if tracer is not None else _default_tracer()

    def start_session(self, spec: Any, policy: Any) -> AbstractContextManager["RAGTelemetrySpan"]:
        return _SpanContext(
            self._tracer,
            "newsroom.rag.session",
            _session_attributes(spec, policy),
        )

    def start_step(self, step: Any, spec: Any) -> AbstractContextManager["RAGTelemetrySpan"]:
        return _SpanContext(
            self._tracer,
            "newsroom.rag.step",
            _step_attributes(step, spec),
        )


@dataclass
class RAGTelemetrySpan:
    _span: Any

    def add_event(self, event_type: str, payload: dict[str, Any]) -> None:
        _call(
            self._span,
            "add_event",
            event_type,
            attributes=_event_attributes(event_type, payload),
        )

    def finish_session(self, *, status: RAGSessionStatus, decision: Any, metrics: Any) -> None:
        attrs = _session_finish_attributes(status=status, decision=decision, metrics=metrics)
        _set_attributes(self._span, attrs)
        if status in (RAGSessionStatus.FAILED, RAGSessionStatus.HALTED, RAGSessionStatus.INSUFFICIENT_EVIDENCE):
            _mark_error(self._span, str(getattr(decision, "reason", "") or status.value))

    def finish_step(self, result: Any) -> None:
        attrs = _step_finish_attributes(result)
        _set_attributes(self._span, attrs)
        if attrs.get("newsroom.rag.step.error_count", 0):
            _mark_error(self._span, "rag step returned errors")

    def record_exception(self, exc: BaseException) -> None:
        _call(self._span, "record_exception", exc)
        _mark_error(self._span, str(exc))

    def trace_metadata(self) -> dict[str, str]:
        return _span_context_metadata(self._span)


class _SpanContext(AbstractContextManager[RAGTelemetrySpan]):
    def __init__(self, tracer: Any, name: str, attributes: dict[str, Any]) -> None:
        self._tracer = tracer
        self._name = name
        self._attributes = _safe_attributes(attributes)
        self._context: Any | None = None
        self._active: RAGTelemetrySpan | None = None

    def __enter__(self) -> RAGTelemetrySpan:
        self._context = self._tracer.start_as_current_span(
            self._name,
            attributes=self._attributes,
        )
        span = self._context.__enter__()
        self._active = RAGTelemetrySpan(span)
        return self._active

    def __exit__(self, exc_type: Any, exc: BaseException | None, traceback: Any) -> bool | None:
        if exc is not None and self._active is not None:
            self._active.record_exception(exc)
        if self._context is None:
            return None
        return self._context.__exit__(exc_type, exc, traceback)


class _NoopTracer:
    def start_as_current_span(self, _name: str, *, attributes: dict[str, Any] | None = None) -> "_NoopSpanContext":
        return _NoopSpanContext()


class _NoopSpanContext(AbstractContextManager["_NoopSpan"]):
    def __enter__(self) -> "_NoopSpan":
        return _NoopSpan()

    def __exit__(self, exc_type: Any, exc: BaseException | None, traceback: Any) -> None:
        return None


class _NoopSpan:
    def set_attribute(self, key: str, value: Any) -> None:
        return None

    def add_event(self, name: str, *, attributes: dict[str, Any] | None = None) -> None:
        return None

    def record_exception(self, exc: BaseException) -> None:
        return None

    def set_status(self, status: Any) -> None:
        return None


def _default_tracer() -> Any:
    if _otel_trace is None:
        return _NoopTracer()
    return _otel_trace.get_tracer(TRACER_NAME)


def _session_attributes(spec: Any, policy: Any) -> dict[str, Any]:
    scope = _session_scope_metadata(spec)
    attrs = {
        "newsroom.rag.session_id": getattr(spec, "session_id", ""),
        "newsroom.rag.run_id": getattr(spec, "run_id", ""),
        "newsroom.rag.workflow_id": getattr(spec, "workflow_id", ""),
        "newsroom.rag.step_id": getattr(spec, "step_id", ""),
        "newsroom.rag.query_hash": _hash_text(getattr(getattr(spec, "goal", None), "question", "")),
        "newsroom.rag.required_evidence_types": list(getattr(getattr(spec, "goal", None), "required_evidence_types", ())),
        "newsroom.rag.generation_enabled": bool(getattr(policy, "generation_enabled", False)),
        "newsroom.rag.max_generation_attempts": int(getattr(policy, "max_generation_attempts", 0) or 0),
    }
    budget = getattr(spec, "budget", None)
    for field_name in (
        "max_rounds",
        "max_replans",
        "max_queries",
        "max_source_reads",
        "max_memory_hits",
        "max_context_items",
        "max_context_tokens",
        "max_worker_calls",
    ):
        attrs[f"newsroom.rag.budget.{field_name}"] = int(getattr(budget, field_name, 0) or 0)
    if scope.get("tenant_id"):
        attrs["newsroom.rag.tenant_id"] = scope["tenant_id"]
    return attrs


def _step_attributes(step: Any, spec: Any) -> dict[str, Any]:
    operation = getattr(step, "operation", "")
    operation_value = operation.value if isinstance(operation, RetrievalOperation) else str(operation)
    attrs = {
        "newsroom.rag.session_id": getattr(spec, "session_id", ""),
        "newsroom.rag.step.step_id": getattr(step, "step_id", ""),
        "newsroom.rag.step.operation": operation_value,
        "newsroom.rag.step.scope": getattr(step, "corpus", "") or "default",
        "newsroom.rag.step.has_query": bool(str(getattr(step, "query", "") or "").strip()),
        "newsroom.rag.step.query_hash": _hash_text(getattr(step, "query", "") or ""),
        "newsroom.rag.step.max_results": int(getattr(step, "max_results", 0) or 0),
        "newsroom.rag.step.max_source_reads": int(getattr(step, "max_source_reads", 0) or 0),
    }
    return attrs


def _session_finish_attributes(*, status: RAGSessionStatus, decision: Any, metrics: Any) -> dict[str, Any]:
    attrs = {
        "newsroom.rag.status": status.value,
        "newsroom.rag.decision_type": getattr(getattr(decision, "decision_type", None), "value", ""),
    }
    values = metrics.to_dict() if hasattr(metrics, "to_dict") else dict(metrics or {})
    for key in (
        "transcript_event_count",
        "accepted_evidence_count",
        "rejected_evidence_count",
        "conflicting_evidence_count",
        "memory_context_count",
        "artifact_ref_count",
        "answer_present",
        "answer_abstained",
        "answer_attempts",
        "supplemental_rounds_started",
        "supplemental_rounds_completed",
        "supplemental_rounds_failed",
        "supplemental_rounds_skipped",
        "gate_failures_count",
    ):
        attrs[f"newsroom.rag.metrics.{key}"] = values.get(key)
    budget = values.get("budget_snapshot") if isinstance(values.get("budget_snapshot"), dict) else {}
    for key, value in budget.items():
        attrs[f"newsroom.rag.budget.used.{key}"] = value
    return attrs


def _step_finish_attributes(result: Any) -> dict[str, Any]:
    return {
        "newsroom.rag.step.result_item_count": len(getattr(result, "items", ()) or ()),
        "newsroom.rag.step.source_ref_count": len(getattr(result, "source_refs", ()) or ()),
        "newsroom.rag.step.memory_ref_count": len(getattr(result, "memory_refs", ()) or ()),
        "newsroom.rag.step.artifact_ref_count": len(getattr(result, "artifact_refs", ()) or ()),
        "newsroom.rag.step.error_count": len(getattr(result, "errors", ()) or ()),
        "newsroom.rag.step.latency_ms": int(getattr(result, "latency_ms", 0) or 0),
    }


def _event_attributes(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    attrs: dict[str, Any] = {"newsroom.rag.event_type": event_type}
    for key in ("round_index", "generation_attempt", "max_generation_attempts"):
        if key in payload:
            attrs[f"newsroom.rag.event.{key}"] = payload[key]
    if "supplemental" in payload:
        attrs["newsroom.rag.event.supplemental"] = bool(payload["supplemental"])
    if isinstance(payload.get("gate_results"), (tuple, list)):
        gate_results = [item for item in payload["gate_results"] if isinstance(item, dict)]
        attrs["newsroom.rag.event.gate_count"] = len(gate_results)
        attrs["newsroom.rag.event.failed_gate_count"] = sum(1 for item in gate_results if item.get("passed") is False)
    for key, attr_key in (
        ("accepted", "accepted_evidence_count"),
        ("rejected", "rejected_evidence_count"),
        ("conflicting", "conflicting_evidence_count"),
        ("unsupported_claims", "unsupported_claim_count"),
    ):
        if isinstance(payload.get(key), (tuple, list)):
            attrs[f"newsroom.rag.event.{attr_key}"] = len(payload[key])
    if isinstance(payload.get("pack"), dict):
        pack = payload["pack"]
        attrs["newsroom.rag.event.context_pack_id"] = str(pack.get("pack_id") or "")
        if isinstance(pack.get("accepted_evidence"), list):
            attrs["newsroom.rag.event.accepted_evidence_count"] = len(pack["accepted_evidence"])
    if payload.get("context_pack_id"):
        attrs["newsroom.rag.event.context_pack_id"] = str(payload["context_pack_id"])
    decision_type = payload.get("decision_type")
    if decision_type:
        attrs["newsroom.rag.event.decision_type"] = str(decision_type)
    status = payload.get("status")
    if status:
        attrs["newsroom.rag.event.status"] = str(status)
    return attrs


def _session_scope_metadata(spec: Any) -> dict[str, str]:
    values: dict[str, str] = {}
    for source in (getattr(getattr(spec, "goal", None), "metadata", {}), getattr(spec, "metadata", {}), getattr(spec, "source_policy", {})):
        if not isinstance(source, dict):
            continue
        for key in ("tenant_id",):
            value = str(source.get(key) or "").strip()
            if value and key not in values:
                values[key] = value
    return values


def _safe_attributes(attrs: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in attrs.items():
        value = _attribute_value(value)
        if value is not None:
            clean[str(key)] = value
    return clean


def _attribute_value(value: Any) -> Any:
    value = to_jsonable(value)
    if value is None:
        return None
    if isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        values = [_attribute_value(item) for item in value]
        values = [item for item in values if isinstance(item, (bool, int, float, str))]
        if not values:
            return None
        first_type = type(values[0])
        if all(isinstance(item, first_type) for item in values):
            return values
        return [str(item) for item in values]
    return str(value)


def _set_attributes(span: Any, attrs: dict[str, Any]) -> None:
    for key, value in _safe_attributes(attrs).items():
        _call(span, "set_attribute", key, value)


def _mark_error(span: Any, description: str) -> None:
    if _OtelStatus is not None and _OtelStatusCode is not None:
        _call(span, "set_status", _OtelStatus(_OtelStatusCode.ERROR, description))
        return
    _call(span, "set_attribute", "newsroom.rag.error", True)
    if description:
        _call(span, "set_attribute", "newsroom.rag.error_description", description[:160])


def _span_context_metadata(span: Any) -> dict[str, str]:
    if not hasattr(span, "get_span_context"):
        return {}
    context = span.get_span_context()
    trace_id = _format_trace_value(getattr(context, "trace_id", None), width=32)
    span_id = _format_trace_value(getattr(context, "span_id", None), width=16)
    out: dict[str, str] = {}
    if trace_id:
        out["trace_id"] = trace_id
    if span_id:
        out["root_span_id"] = span_id
    return out


def _format_trace_value(value: Any, *, width: int) -> str | None:
    if value is None:
        return None
    if isinstance(value, int):
        if value <= 0:
            return None
        return f"{value:0{width}x}"
    text = str(value).strip()
    return text or None


def _hash_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return sha256(text.encode("utf-8")).hexdigest()[:16]


def _call(target: Any, method_name: str, *args: Any, **kwargs: Any) -> Any:
    method = getattr(target, method_name, None)
    if method is None:
        return None
    return method(*args, **kwargs)


__all__ = ["RAGTelemetry", "RAGTelemetrySpan", "TRACER_NAME"]
