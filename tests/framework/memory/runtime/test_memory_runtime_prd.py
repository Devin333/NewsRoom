from framework.memory import (
    InMemoryMemoryStore,
    MemoryKind,
    MemoryRecord,
    MemoryRuntime,
    MemoryScope,
)


def test_runtime_write_recall_promote_and_invalidate() -> None:
    runtime = MemoryRuntime(InMemoryMemoryStore())
    write = runtime.write(
        records=[
            MemoryRecord(
                memory_id="mem-1",
                content="Memory runtime recall can find stable facts.",
                kind=MemoryKind.SEMANTIC,
                scope=MemoryScope.WORKFLOW,
                refs={"run_id": "run-1"},
            )
        ],
        actor="workflow",
    )

    recall = runtime.recall("stable facts")
    promoted = runtime.promote("mem-1", target_scope=MemoryScope.GLOBAL, reason="stable")
    invalidated = runtime.invalidate("mem-1", reason="outdated")

    assert write.written_count == 1
    assert recall.result_count == 1
    assert promoted.written_count == 1
    assert runtime.get("mem-1").scope == MemoryScope.GLOBAL
    assert invalidated.written_count == 1
    assert runtime.get("mem-1").is_invalidated() is True
