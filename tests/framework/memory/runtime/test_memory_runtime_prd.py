from framework.memory import (
    InMemoryMemoryStore,
    MemoryKind,
    MemoryRecord,
    MemoryRuntime,
    MemoryScope,
)
from framework.shared.graph_identity import GraphExecutionIdentity


def test_runtime_write_recall_promote_and_invalidate() -> None:
    runtime = MemoryRuntime(InMemoryMemoryStore())
    identity = GraphExecutionIdentity(
        run_id="run-1",
        graph_id="graph-1",
        graph_version="v1",
        graph_ref="graph-1@v1",
        graph_checksum="sha256:" + "a" * 64,
        node_id="memory-node",
        node_instance_id="memory-instance",
        activity_id="activity-1",
        attempt=1,
    )
    write = runtime.write(
        records=[
            MemoryRecord(
                memory_id="mem-1",
                content="Memory runtime recall can find stable facts.",
                kind=MemoryKind.SEMANTIC,
                scope=MemoryScope.GRAPH,
                refs={"run_id": "run-1"},
            )
        ],
        actor="graph",
        execution_identity=identity,
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
