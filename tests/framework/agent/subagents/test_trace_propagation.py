from __future__ import annotations

from contextlib import AbstractContextManager
from importlib import import_module
from types import SimpleNamespace
from typing import Any

import pytest

from framework.agent.subagents import LocalSubAgentExecutor, SubAgentTask
from framework.events import (
    EventTelemetry,
    TelemetryInstrumentationScope,
    TelemetryResource,
    W3CSpanContext,
    W3CTracePropagator,
    current_trace_context,
)


runner_module = import_module("framework.agent.loop.runner")


def test_subagent_handoff_extracts_child_scope_and_records_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    producer = W3CSpanContext.root()
    observed: list[W3CSpanContext | None] = []
    invocations: list[tuple[dict[str, Any], dict[str, Any]]] = []

    class _AgentRunner:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        def run(self, agent: Any, inputs: dict[str, Any], **kwargs: Any):
            context = current_trace_context()
            observed.append(
                context if isinstance(context, W3CSpanContext) else None
            )
            invocations.append((inputs, kwargs))
            return SimpleNamespace(
                success=True,
                output={"checked": inputs["subagent_task"]},
                diagnostics=None,
                error=None,
                events=[],
                metrics=SimpleNamespace(to_dict=lambda: {}),
                llm_call_artifacts=[],
                iterations=1,
            )

    monkeypatch.setattr(runner_module, "AgentRunner", _AgentRunner)
    backend = _Backend()
    executor = LocalSubAgentExecutor(
        agents={"critic": object()},
        llm_client=object(),
        tool_registry=object(),
        allow_nested_subagents=True,
        telemetry=EventTelemetry(backend),
    )
    task = SubAgentTask(
        parent_agent_id="parent",
        child_agent_id="critic",
        task="check evidence",
        trace_carrier=W3CTracePropagator().inject(producer),
        metadata={
            "session_id": "retired-shared-session",
            "run_id": "run-1",
            "workflow_id": "workflow-1",
            "step_id": "step-1",
            "workflow_checkpoint_id": "checkpoint-1",
        },
    )

    result = executor.run(task)

    assert result.success is True
    child_inputs, runner_kwargs = invocations[0]
    assert child_inputs["run_id"] == "run-1"
    assert child_inputs["workflow_id"] == "workflow-1"
    assert "session_id" not in child_inputs
    assert runner_kwargs["run_id"] == "run-1"
    assert runner_kwargs["step_id"] == "step-1"
    assert runner_kwargs["workflow_checkpoint_id"] == "checkpoint-1"
    context = observed[0]
    assert isinstance(context, W3CSpanContext)
    assert context.trace_id == producer.trace_id
    assert context.parent_span_id == producer.span_id
    assert current_trace_context() is None
    span = backend.started[0]
    assert span["name"] == "newsroom.subagent.execute"
    assert len(span["links"]) == 1
    assert span["links"][0].context.span_id == producer.span_id
    assert span["links"][0].attributes["newsroom.link.relationship"] == "subagent_handoff"


@pytest.mark.parametrize(
    "carrier",
    [
        {"authorization": "Bearer secret"},
        {"traceparent": "malformed\r\ninjected: true"},
        {"traceparent": "x" * 257},
        {"tracestate": "x" * 513},
        {"baggage": "x" * 8193},
        {"TraceParent": "first", "traceparent": "second"},
    ],
)
def test_subagent_task_rejects_non_trace_or_injected_headers(
    carrier: dict[str, str],
) -> None:
    with pytest.raises(ValueError):
        SubAgentTask(
            parent_agent_id="parent",
            child_agent_id="critic",
            task="check",
            trace_carrier=carrier,
        )


def test_subagent_trace_carrier_is_an_immutable_input_snapshot() -> None:
    traceparent = f"00-{'1' * 32}-{'2' * 16}-01"
    source = {"TraceParent": traceparent}

    task = SubAgentTask(
        parent_agent_id="parent",
        child_agent_id="critic",
        task="check",
        trace_carrier=source,
    )
    source["TraceParent"] = "mutated"

    assert dict(task.trace_carrier) == {"traceparent": traceparent}
    with pytest.raises(TypeError):
        task.trace_carrier["traceparent"] = "mutated"  # type: ignore[index]


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
        self.resource = TelemetryResource(service_name="newsroom-subagent-test")
        self.scope = TelemetryInstrumentationScope(
            name="tests.framework.agent.subagents",
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
