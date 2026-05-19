from datetime import UTC, datetime, timedelta

import pytest

from core.framework.memory import MemoryKind, MemoryQuery, MemoryRecord, MemoryScope, TimeWindow


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


def test_memory_scope_includes_user_scope() -> None:
    assert MemoryScope.USER.value == "user"


def test_memory_query_can_use_filters_without_text() -> None:
    query = MemoryQuery(query="", filters={"run_id": "run-1"})

    assert query.query == ""
    assert query.filters == {"run_id": "run-1"}


def test_memory_query_rejects_empty_query_without_filters_or_kinds() -> None:
    with pytest.raises(ValueError, match="query, filters, or kinds"):
        MemoryQuery(query="")


def test_time_window_serializes_and_validates_order() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=1)
    window = TimeWindow(start=start, end=end)

    assert window.to_dict()["start"] == "2026-01-01T00:00:00Z"

    with pytest.raises(ValueError, match="start must be before end"):
        TimeWindow(start=end, end=start)


def test_memory_record_rejects_invalid_expiry_and_sensitive_keys() -> None:
    created_at = datetime(2026, 1, 1, tzinfo=UTC)

    with pytest.raises(ValueError, match="expires_at"):
        MemoryRecord(
            content="old memory",
            created_at=created_at,
            expires_at=created_at - timedelta(seconds=1),
        )

    with pytest.raises(ValueError, match="sensitive key"):
        MemoryRecord(content="secret metadata", metadata={"api_key": "hidden"})

    with pytest.raises(ValueError, match="sensitive key"):
        MemoryRecord(content="secret ref", refs={"token": "hidden"})
