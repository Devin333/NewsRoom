from __future__ import annotations

import json

from framework.memory import InMemoryMemoryStore, MemoryRecord, MemoryRuntime


def test_memory_recall_result_includes_operation_trace() -> None:
    runtime = MemoryRuntime(
        InMemoryMemoryStore(
            [
                MemoryRecord(memory_id="mem-1", content="agent memory improves recall"),
                MemoryRecord(memory_id="mem-2", content="unrelated note"),
            ]
        )
    )

    result = runtime.recall("agent memory")

    assert result.result_count >= 1
    assert result.operation_trace is not None
    assert result.operation_trace.operation_type == "recall"
    assert result.operation_trace.query == "agent memory"
    assert result.operation_trace.duration_ms is not None
    assert result.operation_trace.candidate_count >= 1
    assert result.operation_trace.selected_count == result.result_count
    assert result.operation_trace.scores
    assert result.operation_trace.scores[0]["memory_id"] == "mem-1"
    assert result.policy_decision["allowed"] is True


def test_memory_recall_trace_to_dict_keeps_legacy_fields_json_safe() -> None:
    runtime = MemoryRuntime(
        InMemoryMemoryStore([MemoryRecord(memory_id="mem-1", content="workflow memory")])
    )

    payload = runtime.recall("workflow").to_dict()

    assert payload["query"] == "workflow"
    assert payload["result_count"] == 1
    assert payload["results"][0]["memory_id"] == "mem-1"
    assert payload["operation_trace"]["operation_type"] == "recall"
    json.dumps(payload)
