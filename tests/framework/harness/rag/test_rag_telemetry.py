from __future__ import annotations

from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import Any

import pytest

from framework.harness import FakeMemoryPort, FakeRAGPlanner, fake_rag_session_spec
from framework.harness.rag.fake import fake_reader_repair_memory, fake_research_evidence_packs
from framework.harness.rag.models import RAGSessionStatus
from framework.harness.rag.session import BoundedRAGSessionController
from framework.harness.rag.telemetry import RAGTelemetry
from framework.harness.retrieval.fake import FakeRetrievalPort


def test_rag_otel_records_session_step_events_and_safe_metrics() -> None:
    tracer = _RecordingTracer()
    base = fake_rag_session_spec()
    spec = replace(
        base,
        goal=replace(
            base.goal,
            question="What sensitive method does the paper use?",
            metadata={
                **base.goal.metadata,
                "tenant_id": "tenant-a",
                "user_id": "user-1",
                "memory_namespace": "research:tenant:tenant-a:user:user-1",
            },
        ),
        metadata={
            **base.metadata,
            "tenant_id": "tenant-a",
            "user_id": "user-1",
            "memory_namespace": "research:tenant:tenant-a:user:user-1",
        },
    )
    controller = BoundedRAGSessionController(
        retrieval=FakeRetrievalPort(fake_research_evidence_packs()[:1]),
        planner=FakeRAGPlanner(),
        memory=FakeMemoryPort(fake_reader_repair_memory()),
        telemetry=RAGTelemetry(tracer=tracer),
    )

    result = controller.run(spec)

    session_span = tracer.spans[0]
    step_spans = [span for span in tracer.spans if span.name == "newsroom.rag.step"]
    assert session_span.name == "newsroom.rag.session"
    assert step_spans
    assert session_span.attributes["newsroom.rag.status"] == result.status.value
    assert session_span.attributes["newsroom.rag.decision_type"] == result.decision.decision_type.value
    assert session_span.attributes["newsroom.rag.metrics.accepted_evidence_count"] == 1
    assert result.metrics is not None
    assert {
        "tenant_id",
        "user_id",
        "memory_namespace",
        "trace_id",
        "root_span_id",
        "context_pack_id",
    }.isdisjoint(result.metrics.to_dict())

    first_step = step_spans[0]
    assert first_step.attributes["newsroom.rag.step.operation"] == "search_corpus"
    assert first_step.attributes["newsroom.rag.step.result_item_count"] == 1
    assert first_step.attributes["newsroom.rag.step.source_ref_count"] > 0
    assert any(event.name == "rag_session_started" for event in session_span.events)
    assert any(event.name == "rag_source_verified" for event in session_span.events)

    forbidden_fragments = (
        "What sensitive method does the paper use?",
        "The method section describes",
        "user-1",
        "research:tenant:tenant-a:user:user-1",
    )
    for span in tracer.spans:
        _assert_safe_attributes(span.attributes, forbidden_fragments)
        for event in span.events:
            _assert_safe_attributes(event.attributes, forbidden_fragments)


def test_rag_otel_noop_allows_sessions_without_opentelemetry_dependency() -> None:
    controller = BoundedRAGSessionController(
        retrieval=FakeRetrievalPort(fake_research_evidence_packs()[:1]),
        planner=FakeRAGPlanner(),
        memory=FakeMemoryPort(fake_reader_repair_memory()),
    )

    result = controller.run(fake_rag_session_spec())

    assert result.metrics is not None
    assert result.metrics.transcript_event_count > 0


def test_rag_otel_does_not_forward_raw_exception_to_native_span() -> None:
    tracer = _RecordingTracer()
    telemetry = RAGTelemetry(tracer=tracer)
    secret = "Bearer raw-secret-token"

    with pytest.raises(RuntimeError, match="raw-secret-token"):
        with telemetry.start_session(fake_rag_session_spec(), object()):
            raise RuntimeError(secret)

    span = tracer.spans[0]
    assert span.attributes["newsroom.rag.error_type"] == "RuntimeError"
    assert tracer.contexts[0].exit_args == [(None, None, None)]
    assert secret not in repr(span.attributes)


def test_rag_otel_isolates_tracer_start_and_context_enter_failures() -> None:
    completed: list[str] = []

    for tracer in (_StartThrowingTracer(), _EnterThrowingTracer()):
        with RAGTelemetry(tracer=tracer).start_session(
            fake_rag_session_spec(),
            object(),
        ):
            completed.append(type(tracer).__name__)

    assert completed == ["_StartThrowingTracer", "_EnterThrowingTracer"]


def test_rag_otel_isolates_span_methods_and_exporter_exit_failure() -> None:
    telemetry = RAGTelemetry(tracer=_ThrowingTracer())
    decision = SimpleNamespace(
        decision_type=SimpleNamespace(value="return_context_pack")
    )
    metrics = SimpleNamespace(to_dict=lambda: {})

    with telemetry.start_session(fake_rag_session_spec(), object()) as span:
        span.add_event("safe_event", {"status": "succeeded"})
        span.finish_session(
            status=RAGSessionStatus.SUCCEEDED,
            decision=decision,
            metrics=metrics,
        )
        span.finish_step(SimpleNamespace())
        span.record_exception(RuntimeError("Bearer raw-secret-token"))


def test_rag_otel_drops_unbounded_or_multiline_string_attributes() -> None:
    tracer = _RecordingTracer()

    with RAGTelemetry(tracer=tracer).start_session(
        fake_rag_session_spec(),
        object(),
    ) as span:
        span.add_event(
            "safe_event",
            {
                "status": "line-one\nBearer raw-secret-token",
                "decision_type": "x" * 97,
            },
        )
        span.add_event("unsafe\nevent", {"status": "succeeded"})

    assert len(tracer.spans[0].events) == 1
    assert tracer.spans[0].events[0].attributes == {
        "newsroom.rag.event_type": "safe_event"
    }


def _assert_safe_attributes(attrs: dict[str, Any], forbidden_fragments: tuple[str, ...]) -> None:
    for key, value in attrs.items():
        key_text = str(key)
        assert "user_id" not in key_text
        assert "memory_namespace" not in key_text
        assert "question" not in key_text
        assert "answer_text" not in key_text
        value_text = str(value)
        for fragment in forbidden_fragments:
            assert fragment not in value_text


@dataclass
class _RecordedEvent:
    name: str
    attributes: dict[str, Any]


@dataclass
class _SpanContext:
    trace_id: int
    span_id: int


class _RecordingSpan:
    def __init__(self, name: str, attributes: dict[str, Any], index: int) -> None:
        self.name = name
        self.attributes = dict(attributes)
        self.events: list[_RecordedEvent] = []
        self.exceptions: list[BaseException] = []
        self.statuses: list[Any] = []
        self._context = _SpanContext(trace_id=index, span_id=index)

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def add_event(self, name: str, *, attributes: dict[str, Any] | None = None) -> None:
        self.events.append(_RecordedEvent(name, dict(attributes or {})))

    def record_exception(self, exc: BaseException) -> None:
        self.exceptions.append(exc)

    def set_status(self, status: Any) -> None:
        self.statuses.append(status)

    def get_span_context(self) -> _SpanContext:
        return self._context


class _RecordingSpanContext:
    def __init__(self, tracer: "_RecordingTracer", name: str, attributes: dict[str, Any]) -> None:
        self.tracer = tracer
        self.span = _RecordingSpan(name, attributes, len(tracer.spans) + 1)
        self.exit_args: list[tuple[Any, Any, Any]] = []

    def __enter__(self) -> _RecordingSpan:
        self.tracer.spans.append(self.span)
        return self.span

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.exit_args.append((exc_type, exc, traceback))
        return None


class _RecordingTracer:
    def __init__(self) -> None:
        self.spans: list[_RecordingSpan] = []
        self.contexts: list[_RecordingSpanContext] = []

    def start_as_current_span(self, name: str, *, attributes: dict[str, Any] | None = None):
        context = _RecordingSpanContext(self, name, dict(attributes or {}))
        self.contexts.append(context)
        return context


class _StartThrowingTracer:
    def start_as_current_span(self, name: str, *, attributes: dict[str, Any]):
        raise RuntimeError("tracer unavailable")


class _EnterThrowingContext:
    def __enter__(self):
        raise RuntimeError("span enter failed")

    def __exit__(self, exc_type, exc, traceback):
        raise RuntimeError("span cleanup failed")


class _EnterThrowingTracer:
    def start_as_current_span(self, name: str, *, attributes: dict[str, Any]):
        return _EnterThrowingContext()


class _ThrowingSpan:
    def set_attribute(self, key: str, value: Any) -> None:
        raise RuntimeError("exporter set_attribute failed")

    def add_event(self, name: str, *, attributes: dict[str, Any]) -> None:
        raise RuntimeError("exporter add_event failed")

    def set_status(self, status: Any) -> None:
        raise RuntimeError("exporter set_status failed")


class _ThrowingContext:
    def __enter__(self) -> _ThrowingSpan:
        return _ThrowingSpan()

    def __exit__(self, exc_type, exc, traceback):
        raise RuntimeError("exporter exit failed")


class _ThrowingTracer:
    def start_as_current_span(self, name: str, *, attributes: dict[str, Any]):
        return _ThrowingContext()
