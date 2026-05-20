from __future__ import annotations

from framework.memory import InMemoryMemoryStore, MemoryRecord, MemoryRuntime


def test_recall_policy_deny_records_block_decision_in_operation_trace() -> None:
    runtime = MemoryRuntime(InMemoryMemoryStore([MemoryRecord(content="blocked recall")]))

    result = runtime.recall({"query": "blocked", "namespace": "../private"})

    assert result.result_count == 0
    assert result.policy_decision["decision"] == "block"
    assert result.error_envelope["error_type"] == "MemoryPolicyDenied"
    assert result.operation_trace is not None
    assert result.operation_trace.policy_decision["decision"] == "block"
    assert result.operation_trace.filtered_count == 0
    assert result.operation_trace.duration_ms is not None


def test_write_policy_deny_records_skipped_count_in_operation_trace() -> None:
    runtime = MemoryRuntime(InMemoryMemoryStore())

    result = runtime.write(
        records=[MemoryRecord(memory_id="mem-1", content="blocked write")],
        tenant_id="/bad-tenant",
    )

    assert result.success is False
    assert result.written_count == 0
    assert result.skipped_count == 1
    assert result.policy_decision["decision"] == "block"
    assert result.error_envelope["error_type"] == "MemoryRuntimeError"
    assert result.operation_trace is not None
    assert result.operation_trace.policy_decision["decision"] == "block"
    assert result.operation_trace.candidate_count == 1
    assert result.operation_trace.selected_count == 0
    assert result.operation_trace.filtered_count == 1
