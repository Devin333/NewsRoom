import pytest

from core.framework.memory import (
    InMemoryMemoryStore,
    MemoryConsolidationRequest,
    MemoryContextAssembler,
    MemoryForgetRequest,
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
                content="Workflow runtime can recall semantic memory before LLM calls.",
                kind=MemoryKind.SEMANTIC,
                scope=MemoryScope.WORKFLOW,
                refs={"run_id": "run-1"},
            ),
            MemoryRecord(
                memory_id="mem-unrelated",
                content="Storage maintenance window.",
                kind=MemoryKind.SEMANTIC,
                scope=MemoryScope.WORKFLOW,
                refs={"run_id": "run-1"},
            ),
        ],
        actor="workflow-1",
    )

    recall = runtime.recall(
        MemoryQuery(
            query="workflow runtime memory",
            scopes=[MemoryScope.WORKFLOW],
            kinds=[MemoryKind.SEMANTIC],
            limit=1,
        )
    )

    assert write.written_count == 2
    assert recall.result_count == 1
    assert recall.results[0].memory_id == "mem-agent-runtime"
    assert "mem-agent-runtime" in recall.context_block.memory_ids
    assert "Workflow runtime" in recall.context_block.content


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


def test_memory_runtime_forget_keeps_direct_delete_compatibility() -> None:
    runtime = MemoryRuntime(
        InMemoryMemoryStore(
            [
                MemoryRecord(
                    memory_id="mem-delete",
                    content="Delete this memory.",
                    kind=MemoryKind.SEMANTIC,
                    scope=MemoryScope.SESSION,
                )
            ]
        )
    )

    result = runtime.forget("mem-delete")

    assert result.forgotten_count == 1
    assert result.memory_ids == ["mem-delete"]
    assert runtime.get("mem-delete") is None


def test_memory_runtime_structured_forget_removes_matching_records() -> None:
    runtime = MemoryRuntime(
        InMemoryMemoryStore(
            [
                MemoryRecord(
                    memory_id="mem-delete-1",
                    content="Delete by id.",
                    kind=MemoryKind.SEMANTIC,
                    scope=MemoryScope.SESSION,
                    metadata={"group": "keep"},
                ),
                MemoryRecord(
                    memory_id="mem-delete-2",
                    content="Delete by filter.",
                    kind=MemoryKind.SEMANTIC,
                    scope=MemoryScope.SESSION,
                    metadata={"group": "delete"},
                ),
            ]
        )
    )

    result = runtime.forget(
        MemoryForgetRequest(memory_ids=["mem-delete-1"], filters={"group": "delete"})
    )

    assert result.forgotten_count == 2
    assert result.memory_ids == ["mem-delete-1", "mem-delete-2"]
    assert runtime.get("mem-delete-1") is None
    assert runtime.get("mem-delete-2") is None


def test_memory_runtime_consolidates_matching_records_into_semantic_memory() -> None:
    runtime = MemoryRuntime(
        InMemoryMemoryStore(
            [
                MemoryRecord(
                    memory_id="mem-source-1",
                    content="First source memory.",
                    summary="First source",
                    kind=MemoryKind.EPISODIC,
                    scope=MemoryScope.SESSION,
                    refs={"run_id": "source-run-1"},
                    tags=["alpha"],
                    confidence=0.8,
                    importance=0.6,
                ),
                MemoryRecord(
                    memory_id="mem-source-2",
                    content="Second source memory.",
                    summary="Second source",
                    kind=MemoryKind.OBSERVATION,
                    scope=MemoryScope.SESSION,
                    refs={"run_id": "source-run-2"},
                    tags=["beta"],
                    confidence=0.6,
                    importance=0.9,
                ),
            ]
        )
    )

    result = runtime.consolidate(
        MemoryConsolidationRequest(
            memory_ids=["mem-source-1", "mem-source-2"],
            actor="agent-1",
            run_id="run-1",
            reason="stable summary",
        )
    )

    consolidated = runtime.get(result.memory_ids[0])

    assert result.consolidated_count == 1
    assert result.source_memory_ids == ["mem-source-1", "mem-source-2"]
    assert consolidated is not None
    assert consolidated.kind == MemoryKind.SEMANTIC
    assert consolidated.refs["run_id"] == "run-1"
    assert consolidated.refs["source_memory_ids"] == ["mem-source-1", "mem-source-2"]
    assert consolidated.metadata["reason"] == "stable summary"
    assert "First source" in consolidated.content
    assert "Second source" in consolidated.content


def test_memory_runtime_uses_configured_context_assembler() -> None:
    class StaticAssembler(MemoryContextAssembler):
        def assemble(self, results, *, max_context_tokens):
            block = super().assemble(results[:1], max_context_tokens=1)
            return type(block)(
                content="custom assembler output",
                token_estimate=1,
                memory_ids=block.memory_ids,
            )

    runtime = MemoryRuntime(
        InMemoryMemoryStore(
            [
                MemoryRecord(
                    memory_id="mem-custom-assembler",
                    content="Custom assembler should be used by runtime recall.",
                    kind=MemoryKind.SEMANTIC,
                    scope=MemoryScope.SESSION,
                    refs={"run_id": "run-1"},
                )
            ]
        ),
        assembler=StaticAssembler(),
    )

    result = runtime.recall("custom assembler")

    assert result.context_block.memory_ids == ["mem-custom-assembler"]
    assert result.context_block.content == "custom assembler output"
    assert result.context_block.token_estimate == 1
