from core.framework.memory import MemoryKind, MemoryQuery, MemoryRecord, MemoryScope


def test_memory_record_serializes_generic_memory_fields() -> None:
    record = MemoryRecord(
        memory_id="mem-1",
        kind="semantic",
        scope="workflow",
        summary="Runtime memory",
        content="MemoryRuntime stores generic records.",
        refs={"run_id": "run-1"},
        confidence=0.8,
        importance=0.7,
    )

    payload = record.to_dict()
    restored = MemoryRecord.from_dict(payload)

    assert record.kind == MemoryKind.SEMANTIC
    assert record.scope == MemoryScope.WORKFLOW
    assert payload["memory_id"] == "mem-1"
    assert payload["refs"] == {"run_id": "run-1"}
    assert restored == record


def test_memory_query_accepts_scores_and_filters() -> None:
    query = MemoryQuery.from_dict(
        {
            "query": "agent memory",
            "scopes": ["agent", "workflow"],
            "kinds": ["core", "semantic"],
            "filters": {"run_id": "run-1"},
            "limit": 200,
            "score_threshold": 0.2,
        }
    )

    assert query.limit == 100
    assert query.min_score == 0.2
    assert [scope.value for scope in query.scopes] == ["agent", "workflow"]
    assert [kind.value for kind in query.kinds] == ["core", "semantic"]

