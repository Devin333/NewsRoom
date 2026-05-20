from __future__ import annotations

import json

from framework.memory import InMemoryMemoryStore, MemoryRecord, MemoryRuntime


def test_memory_runtime_contract_write_recall_policy_and_trace() -> None:
    runtime = MemoryRuntime(InMemoryMemoryStore())

    write = runtime.write(
        records=[
            MemoryRecord(
                memory_id="mem-1",
                content="contract memory trace",
                refs={"source": "contract"},
            )
        ]
    )
    recall = runtime.recall("contract memory")
    denied = runtime.write(
        records=[MemoryRecord(memory_id="mem-2", content="blocked", refs={"source": "contract"})],
        namespace="../bad",
    )

    assert write.success is True
    assert write.operation_trace.operation_type == "write"
    assert write.operation_trace.policy_decision["allowed"] is True
    assert recall.result_count == 1
    assert recall.operation_trace.operation_type == "recall"
    assert recall.operation_trace.scores[0]["memory_id"] == "mem-1"
    assert denied.success is False
    assert denied.policy_decision["decision"] == "block"
    assert denied.operation_trace.policy_decision["decision"] == "block"
    json.dumps(write.to_dict())
    json.dumps(recall.to_dict())
    json.dumps(denied.to_dict())
