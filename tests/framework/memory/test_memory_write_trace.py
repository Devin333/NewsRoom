from __future__ import annotations

import json

from framework.memory import InMemoryMemoryStore, MemoryRecord, MemoryRuntime


def test_memory_write_result_includes_operation_trace() -> None:
    runtime = MemoryRuntime(InMemoryMemoryStore())

    result = runtime.write(
        records=[
            MemoryRecord(
                memory_id="mem-1",
                content="write trace",
                refs={"source": "test"},
            )
        ]
    )

    assert result.success is True
    assert result.written_count == 1
    assert result.memory_ids == ["mem-1"]
    assert result.operation_trace is not None
    assert result.operation_trace.operation_type == "write"
    assert result.operation_trace.duration_ms is not None
    assert result.operation_trace.candidate_count == 1
    assert result.operation_trace.selected_count == 1
    assert result.operation_trace.metadata["written_ids"] == ["mem-1"]
    assert result.policy_decision["allowed"] is True


def test_memory_write_trace_to_dict_keeps_legacy_fields_json_safe() -> None:
    runtime = MemoryRuntime(InMemoryMemoryStore())

    payload = runtime.write(
        records=[
            MemoryRecord(
                memory_id="mem-1",
                content="json safe write trace",
                refs={"source": "test"},
            )
        ]
    ).to_dict()

    assert payload["success"] is True
    assert payload["accepted_count"] == 1
    assert payload["written_count"] == 1
    assert payload["memory_ids"] == ["mem-1"]
    assert payload["operation_trace"]["operation_type"] == "write"
    json.dumps(payload)
