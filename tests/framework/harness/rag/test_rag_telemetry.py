from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from framework.harness import FakeMemoryPort, FakeRAGPlanner, fake_rag_session_spec
from framework.harness.rag.fake import fake_reader_repair_memory, fake_research_evidence_packs
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
    assert session_span.attributes["newsroom.rag.tenant_id"] == "tenant-a"
    assert result.metrics is not None
    assert result.metrics.trace_id == "00000000000000000000000000000001"
    assert result.metrics.root_span_id == "0000000000000001"

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
    assert result.metrics.trace_id is None
    assert result.metrics.root_span_id is None


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

    def __enter__(self) -> _RecordingSpan:
        self.tracer.spans.append(self.span)
        return self.span

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None


class _RecordingTracer:
    def __init__(self) -> None:
        self.spans: list[_RecordingSpan] = []

    def start_as_current_span(self, name: str, *, attributes: dict[str, Any] | None = None):
        return _RecordingSpanContext(self, name, dict(attributes or {}))
