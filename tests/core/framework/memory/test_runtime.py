from core.framework.memory import (
    InMemoryMemoryStore,
    MemoryKind,
    MemoryPolicy,
    MemoryQuery,
    MemoryRecord,
    MemoryRuntime,
    MemoryScope,
    inspect_memory_runtime,
)


def test_memory_runtime_writes_recalls_and_builds_context() -> None:
    runtime = MemoryRuntime(InMemoryMemoryStore())
    write = runtime.write(
        records=[
            MemoryRecord(
                memory_id="mem-agent-runtime",
                content="Agent runtime can recall semantic memory before LLM calls.",
                kind=MemoryKind.SEMANTIC,
                scope=MemoryScope.AGENT,
                refs={"run_id": "run-1"},
            ),
            MemoryRecord(
                memory_id="mem-unrelated",
                content="Storage maintenance window.",
                kind=MemoryKind.SEMANTIC,
                scope=MemoryScope.AGENT,
                refs={"run_id": "run-1"},
            ),
        ],
        actor="agent-1",
    )

    recall = runtime.recall(
        MemoryQuery(
            query="agent runtime memory",
            scopes=[MemoryScope.AGENT],
            kinds=[MemoryKind.SEMANTIC],
            limit=1,
        )
    )

    assert write.written_count == 2
    assert recall.result_count == 1
    assert recall.results[0].memory_id == "mem-agent-runtime"
    assert "mem-agent-runtime" in recall.context_block.memory_ids
    assert "Agent runtime" in recall.context_block.content


def test_memory_runtime_diagnostics_exposes_confidence_policy() -> None:
    runtime = MemoryRuntime(
        InMemoryMemoryStore(),
        policy=MemoryPolicy(
            allowed_scopes=[MemoryScope.WORKFLOW],
            allowed_kinds=[MemoryKind.SEMANTIC],
            min_confidence_to_write=0.4,
            min_confidence_to_recall=0.5,
        ),
    )

    payload = inspect_memory_runtime(runtime).to_dict()

    assert payload["policy"]["min_confidence_to_write"] == 0.4
    assert payload["policy"]["min_confidence_to_recall"] == 0.5
