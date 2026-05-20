from __future__ import annotations

from framework.memory import InMemoryMemoryStore, MemoryRecord, MemoryRuntime


def test_memory_recall_default_policy_decision_allows() -> None:
    runtime = MemoryRuntime(InMemoryMemoryStore([MemoryRecord(content="hello memory")]))

    result = runtime.recall("hello")

    assert result.policy_decision["allowed"] is True
    assert result.result_count == 1


def test_memory_write_invalid_namespace_returns_policy_decision_error() -> None:
    runtime = MemoryRuntime(InMemoryMemoryStore())

    result = runtime.write(
        records=[MemoryRecord(content="blocked")],
        namespace="../secrets",
    )

    assert result.written_count == 0
    assert result.skipped_count == 1
    assert result.policy_decision["decision"] == "block"
    assert result.errors
