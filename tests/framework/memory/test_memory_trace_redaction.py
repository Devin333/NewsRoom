from __future__ import annotations

import json

from framework.events import TraceContext
from framework.shared import GraphExecutionIdentity
from framework.memory import InMemoryMemoryStore, MemoryRecord, MemoryRuntime
from framework.memory.diagnostics.trace import MemoryTraceRecorder


def test_memory_operation_trace_redacts_secret_like_query_and_metadata() -> None:
    runtime = MemoryRuntime(InMemoryMemoryStore([MemoryRecord(content="secret trace")]))

    result = runtime.recall("token sk-1234567890abcdef")

    payload = result.operation_trace.to_dict()
    serialized = json.dumps(payload)
    assert "sk-1234567890abcdef" not in serialized
    assert "***REDACTED***" in serialized


def test_memory_runtime_records_operation_event_with_trace_context() -> None:
    recorder = MemoryTraceRecorder()
    trace = TraceContext.root(
        execution_identity=GraphExecutionIdentity(
            run_id="run-1",
            graph_id="test.graph",
            graph_version="1",
            graph_ref="test.graph@1",
            graph_checksum="sha256:" + "a" * 64,
            node_id="stage-1",
            node_instance_id="stage-1:1",
            activity_id="activity-1",
            attempt=1,
        ),
        trace_id="trace-1",
        span_id="step:memory",
    )
    runtime = MemoryRuntime(
        InMemoryMemoryStore([MemoryRecord(memory_id="mem-1", content="trace memory")]),
        trace_context=trace,
        trace_recorder=recorder,
    )

    result = runtime.recall("trace")
    events = recorder.list_events()

    assert len(events) == 1
    payload = events[0].to_dict()
    assert payload["event_type"] == "memory_operation"
    assert payload["trace_id"] == "trace-1"
    assert payload["span_id"] == result.operation_trace.span_id
    assert payload["parent_span_id"] == "step:memory"
    assert payload["payload"]["operation_id"] == result.operation_trace.operation_id
    assert payload["payload"]["query"] == "trace"
