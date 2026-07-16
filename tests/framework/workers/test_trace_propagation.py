from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any

import pytest

from framework.events import (
    EventTelemetry,
    TelemetryInstrumentationScope,
    TelemetryResource,
    W3CSpanContext,
    W3CTracePropagator,
    current_trace_context,
    trace_context_scope,
)
from framework.workers import (
    InMemoryTaskQueue,
    Task,
    TaskDispatcher,
    TaskHandlerRegistry,
    TaskResult,
)


def test_worker_task_round_trip_queue_injection_and_consumer_link() -> None:
    producer = W3CSpanContext.root()
    outer = W3CSpanContext.root()
    queue = InMemoryTaskQueue()
    task = Task(task_type="demo", payload={"value": 7}, queue_name="q")

    with trace_context_scope(producer):
        queue.enqueue(task)

    restored = Task.from_dict(task.to_dict())
    extracted = W3CTracePropagator().extract_span(restored.trace_carrier)
    assert extracted.context.trace_id == producer.trace_id
    assert extracted.context.span_id == producer.span_id

    handler = _Handler()
    registry = TaskHandlerRegistry()
    registry.register(handler)
    backend = _Backend()
    restored.attempts = 2
    dispatcher = TaskDispatcher(
        registry,
        telemetry=EventTelemetry(backend),
    )

    with trace_context_scope(outer):
        result = dispatcher.dispatch(restored)
        assert current_trace_context() is outer

    assert result.success is True
    context = handler.contexts[0]
    assert isinstance(context, W3CSpanContext)
    assert context.trace_id == producer.trace_id
    assert context.parent_span_id == producer.span_id
    span = backend.started[0]
    assert span["attributes"]["newsroom.worker.attempt_bucket"] == "retry_low"
    assert len(span["links"]) == 1
    assert span["links"][0].context.span_id == producer.span_id
    assert span["links"][0].attributes["newsroom.link.relationship"] == "worker_message"


@pytest.mark.parametrize(
    "carrier",
    [
        {"authorization": "Bearer secret"},
        {"traceparent": "valid-looking\r\ninjected: true"},
        {"traceparent": "x" * 257},
        {"tracestate": "x" * 513},
        {"baggage": "x" * 8193},
        {"TraceParent": "first", "traceparent": "second"},
    ],
)
def test_worker_task_rejects_unbounded_or_non_trace_carriers(
    carrier: dict[str, str],
) -> None:
    with pytest.raises(ValueError):
        Task(task_type="demo", payload={}, trace_carrier=carrier)


@dataclass
class _Handler:
    task_type: str = "demo"

    def __post_init__(self) -> None:
        self.contexts: list[W3CSpanContext | None] = []

    def handle(self, task: Task) -> TaskResult:
        context = current_trace_context()
        self.contexts.append(
            context if isinstance(context, W3CSpanContext) else None
        )
        return TaskResult.success(task.task_id, {"seen": task.payload["value"]})


class _Span:
    def set_attribute(self, key: str, value: Any) -> None:
        return None

    def add_event(self, name: str, *, attributes: dict[str, Any]) -> None:
        return None


class _Scope(AbstractContextManager[_Span]):
    def __enter__(self) -> _Span:
        return _Span()

    def __exit__(self, exc_type: Any, exc: BaseException | None, traceback: Any) -> bool:
        return False


class _Backend:
    def __init__(self) -> None:
        self.resource = TelemetryResource(service_name="newsroom-worker-test")
        self.scope = TelemetryInstrumentationScope(
            name="tests.framework.workers",
            version="1",
        )
        self.started: list[dict[str, Any]] = []

    def start_span(self, name: str, *, attributes: Any, links: Any) -> _Scope:
        self.started.append(
            {
                "name": name,
                "attributes": dict(attributes),
                "links": tuple(links),
            }
        )
        return _Scope()

    def add_counter(self, name: str, value: int, *, attributes: Any) -> None:
        return None
