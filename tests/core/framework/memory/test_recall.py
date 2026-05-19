from core.framework.memory import (
    InMemoryMemoryStore,
    MemoryContextAssembler,
    MemoryKind,
    MemoryPolicy,
    MemoryQuery,
    MemoryRecord,
    MemoryRuntime,
    MemoryScope,
    MemorySearchResult,
)


def test_memory_context_assembler_truncates_first_result_to_budget() -> None:
    record = MemoryRecord(
        memory_id="mem-long",
        content="long memory " * 100,
        kind=MemoryKind.SEMANTIC,
        scope=MemoryScope.WORKFLOW,
    )

    block = MemoryContextAssembler().assemble(
        [MemorySearchResult(record=record, score=0.9, source="keyword")],
        max_context_tokens=10,
    )

    assert block.memory_ids == ["mem-long"]
    assert block.token_estimate <= 10
    assert block.content.endswith("...")


def test_memory_recall_result_includes_source_and_diagnostics() -> None:
    runtime = MemoryRuntime(
        InMemoryMemoryStore(
            [
                MemoryRecord(
                    memory_id="mem-runtime",
                    content="Workflow memory runtime can assemble recall diagnostics.",
                    kind=MemoryKind.SEMANTIC,
                    scope=MemoryScope.WORKFLOW,
                ),
                MemoryRecord(
                    memory_id="mem-other",
                    content="Unrelated storage note.",
                    kind=MemoryKind.SEMANTIC,
                    scope=MemoryScope.WORKFLOW,
                ),
            ]
        ),
        policy=MemoryPolicy(
            allowed_scopes=[MemoryScope.WORKFLOW],
            allowed_kinds=[MemoryKind.SEMANTIC],
            max_recall_results=1,
            max_context_tokens=20,
        ),
    )

    result = runtime.recall(
        MemoryQuery(
            query="workflow memory runtime diagnostics",
            scopes=[MemoryScope.WORKFLOW],
            kinds=[MemoryKind.SEMANTIC],
            limit=5,
        )
    )
    payload = result.to_dict()

    assert result.result_count == 1
    assert result.results[0].source == "keyword"
    assert payload["results"][0]["source"] == "keyword"
    assert payload["diagnostics"]["requested_query"]["limit"] == 5
    assert payload["diagnostics"]["effective_query"]["limit"] == 1
    assert payload["diagnostics"]["result_count"] == 1
    assert payload["diagnostics"]["context_token_budget"] == 20
    assert payload["diagnostics"]["context_token_estimate"] == result.context_block.token_estimate
    assert payload["diagnostics"]["memory_ids"] == result.context_block.memory_ids
