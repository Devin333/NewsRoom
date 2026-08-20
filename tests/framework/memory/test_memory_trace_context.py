from __future__ import annotations

from framework.events import TraceContext
from framework.shared import GraphExecutionIdentity
from framework.memory.diagnostics.trace import MemoryTraceEvent, MemoryTraceRecorder


def test_memory_trace_event_keeps_trace_context_fields() -> None:
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
        span_id="step:s1",
    ).child(span_id="memory:recall-1", memory_operation_id="recall-1")
    event = MemoryTraceEvent(
        event_type="memory_recall_completed",
        memory_id="mem-1",
        payload={"count": 1},
        trace_context=trace,
    )
    recorder = MemoryTraceRecorder()
    recorder.record(event)

    payload = recorder.list_events()[0].to_dict()

    assert payload["trace_id"] == "trace-1"
    assert payload["span_id"] == "memory:recall-1"
    assert payload["parent_span_id"] == "step:s1"
    assert payload["run_id"] == "run-1"
