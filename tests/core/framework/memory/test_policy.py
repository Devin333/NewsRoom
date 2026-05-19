import pytest

from core.framework.memory import (
    DEFAULT_AGENT_MEMORY_POLICY,
    MemoryPolicyDenied,
    MemoryKind,
    MemoryPolicy,
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
    MemoryValidationError,
)


def test_memory_policy_rejects_global_write_without_permission() -> None:
    policy = MemoryPolicy(
        allowed_scopes=[MemoryScope.GLOBAL],
        allowed_kinds=[MemoryKind.SEMANTIC],
        allow_global_write=False,
    )
    record = MemoryRecord(
        content="Global fact",
        kind=MemoryKind.SEMANTIC,
        scope=MemoryScope.GLOBAL,
    )

    with pytest.raises(PermissionError, match="global memory writes"):
        policy.validate_write(record)


def test_memory_policy_requires_refs_when_enabled() -> None:
    policy = MemoryPolicy(
        allowed_scopes=[MemoryScope.WORKFLOW],
        allowed_kinds=[MemoryKind.OBSERVATION],
        require_refs=True,
    )
    record = MemoryRecord(
        content="Step observation",
        kind=MemoryKind.OBSERVATION,
        scope=MemoryScope.WORKFLOW,
    )

    with pytest.raises(ValueError, match="refs are required"):
        policy.validate_write(record)

    with pytest.raises(MemoryValidationError, match="refs are required"):
        policy.validate_write(record)


def test_memory_policy_requires_refs_by_default() -> None:
    policy = MemoryPolicy(
        allowed_scopes=[MemoryScope.WORKFLOW],
        allowed_kinds=[MemoryKind.OBSERVATION],
    )
    record = MemoryRecord(
        content="Step observation",
        kind=MemoryKind.OBSERVATION,
        scope=MemoryScope.WORKFLOW,
    )

    with pytest.raises(ValueError, match="refs are required"):
        policy.validate_write(record)


def test_memory_policy_rejects_low_confidence_write() -> None:
    policy = MemoryPolicy(
        allowed_scopes=[MemoryScope.WORKFLOW],
        allowed_kinds=[MemoryKind.SEMANTIC],
        min_confidence_to_write=0.5,
    )
    record = MemoryRecord(
        content="low confidence memory",
        kind=MemoryKind.SEMANTIC,
        scope=MemoryScope.WORKFLOW,
        refs={"run_id": "run-1"},
        confidence=0.2,
    )

    with pytest.raises(PermissionError, match="confidence"):
        policy.validate_write(record)

    with pytest.raises(MemoryPolicyDenied, match="confidence"):
        policy.validate_write(record)


def test_memory_policy_rejects_recall_score_below_minimum() -> None:
    policy = MemoryPolicy(
        allowed_scopes=[MemoryScope.WORKFLOW],
        allowed_kinds=[MemoryKind.SEMANTIC],
        min_confidence_to_recall=0.4,
    )
    query = MemoryQuery(
        query="runtime memory",
        scopes=[MemoryScope.WORKFLOW],
        kinds=[MemoryKind.SEMANTIC],
        min_score=0.2,
    )

    with pytest.raises(PermissionError, match="min_score"):
        policy.validate_recall(query)


def test_memory_policy_filtered_query_applies_minimum_recall_score() -> None:
    policy = MemoryPolicy(
        allowed_scopes=[MemoryScope.WORKFLOW],
        allowed_kinds=[MemoryKind.SEMANTIC],
        min_confidence_to_recall=0.4,
        max_recall_results=5,
    )

    query = policy.filtered_query(MemoryQuery(query="runtime memory", limit=50))

    assert query.limit == 5
    assert query.min_score == 0.4


def test_default_agent_memory_policy_matches_final_prd_defaults() -> None:
    assert DEFAULT_AGENT_MEMORY_POLICY.allow_write is False
    assert DEFAULT_AGENT_MEMORY_POLICY.allow_recall is True
    assert DEFAULT_AGENT_MEMORY_POLICY.require_refs is True
    assert DEFAULT_AGENT_MEMORY_POLICY.max_recall_results == 5
    assert DEFAULT_AGENT_MEMORY_POLICY.max_context_tokens == 1500
    assert [scope.value for scope in DEFAULT_AGENT_MEMORY_POLICY.allowed_scopes] == [
        "session",
        "agent",
        "workflow",
    ]
