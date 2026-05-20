from datetime import UTC, datetime, timedelta

import pytest

from framework.memory import (
    MemoryKind,
    MemoryQuery,
    MemoryRecord,
    MemoryReference,
    MemoryScope,
    MemoryScore,
    MemorySearchResult,
    TimeWindow,
)


def test_memory_record_accepts_reference_list_and_exposes_legacy_refs() -> None:
    record = MemoryRecord(
        content="Framework memory supports references.",
        refs=[MemoryReference(ref_type="artifact", ref_id="artifact-1")],
        namespace="agent",
        tenant_id="tenant-1",
    )

    assert record.refs == {"artifact": "artifact-1"}
    assert record.references()[0].stable_key() == "artifact:artifact-1"
    assert record.namespace == "agent"
    assert record.tenant_id == "tenant-1"


def test_memory_scope_and_kind_helpers() -> None:
    assert MemoryScope.default() == MemoryScope.SESSION
    assert MemoryScope.USER.is_persistent() is True
    assert MemoryScope.WORKING.is_runtime_local() is True
    assert MemoryKind.default() == MemoryKind.SEMANTIC
    assert MemoryKind.DECISION.is_long_term_candidate() is True
    assert MemoryKind.OBSERVATION.is_short_lived() is True


def test_time_window_contains_and_overlaps() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=1)
    window = TimeWindow(start=start, end=end)

    assert window.contains(start + timedelta(minutes=10)) is True
    assert window.overlaps(TimeWindow(start=end, end=end + timedelta(hours=1))) is True

    with pytest.raises(ValueError, match="start must be before end"):
        TimeWindow(start=end, end=start)


def test_score_and_search_result_keep_float_score_compatibility() -> None:
    score = MemoryScore(relevance=0.6, confidence=0.8)
    result = MemorySearchResult(
        record=MemoryRecord(content="Scored memory"),
        score=0.7,
        score_detail=score,
    )

    assert result.score == 0.7
    assert result.score_detail.compute() > 0
    assert result.to_dict()["score_detail"]["confidence"] == 0.8


def test_query_filters_namespace_and_tags_round_trip() -> None:
    query = MemoryQuery.from_dict(
        {
            "query": "memory",
            "tags": ["runtime"],
            "namespace": "agent",
            "tenant_id": "tenant-1",
        }
    )

    assert query.to_dict()["tags"] == ["runtime"]
    assert query.namespace == "agent"
    assert query.tenant_id == "tenant-1"
