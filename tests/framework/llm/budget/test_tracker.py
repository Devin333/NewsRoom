from __future__ import annotations

import pytest

from framework.governance.budget import BudgetHistoryError, BudgetScopeType
from framework.llm.budget import GlobalBudgetPolicy, GlobalBudgetTracker
from framework.llm.models import TokenUsage
from framework.shared.graph_identity import GraphExecutionIdentity


def test_facade_restore_preserves_canonical_identity_and_rejects_policy_drift() -> None:
    source = GlobalBudgetTracker(
        GlobalBudgetPolicy(max_llm_calls=3, max_total_tokens=100),
        run_id="run-source",
    )
    source.record_llm_call(TokenUsage(input_tokens=7, output_tokens=3))
    snapshot = source.canonical_snapshot()

    restored = GlobalBudgetTracker(
        GlobalBudgetPolicy(max_llm_calls=3, max_total_tokens=100),
        run_id="run-resume",
    )
    restored.restore(snapshot)
    assert restored.canonical_snapshot() == snapshot
    assert restored.scope.run_id == "run-source"

    mismatched = GlobalBudgetTracker(
        GlobalBudgetPolicy(max_llm_calls=4, max_total_tokens=100),
        run_id="run-mismatch",
    )
    with pytest.raises(BudgetHistoryError, match="policy"):
        mismatched.restore(snapshot)


def test_facade_identity_generation_is_unique_after_restore() -> None:
    tracker = GlobalBudgetTracker(GlobalBudgetPolicy(max_llm_calls=4), run_id="run-id")
    first = tracker.next_operation_identity("operation")
    snapshot = tracker.canonical_snapshot()
    tracker.restore(snapshot)
    second = tracker.next_operation_identity("operation")

    assert first != second
    assert first.startswith("operation:run-id:")
    assert second.startswith("operation:run-id:")


def test_child_facade_cannot_export_or_restore_authoritative_snapshot() -> None:
    root = GlobalBudgetTracker(GlobalBudgetPolicy(max_llm_calls=2), run_id="run-scope")
    child = root.child_tracker("agent-a", scope_type=BudgetScopeType.AGENT_LOOP)
    sibling = root.child_tracker("agent-b", scope_type=BudgetScopeType.SUBAGENT)
    operation = child.reserve_direct_operation(
        operation_id="child-operation",
        idempotency_key="child-idempotency",
        input_tokens=1,
        output_tokens=0,
    )

    assert operation.operation_id == "child-operation"
    assert child.usage.llm_calls == 1
    assert sibling.usage.llm_calls == 0
    assert root.usage.llm_calls == 1
    with pytest.raises(ValueError, match="root tracker"):
        child.canonical_snapshot()
    with pytest.raises(ValueError, match="root tracker"):
        child.restore(root.canonical_snapshot())


def test_execution_bound_tracker_rejects_cross_activity_rebinding() -> None:
    def identity(activity_id: str) -> GraphExecutionIdentity:
        return GraphExecutionIdentity(
            run_id="run-budget",
            graph_id="research.graph",
            graph_version="v1",
            graph_ref="research.graph@v1",
            graph_checksum="sha256:" + "a" * 64,
            node_id="analyze",
            node_instance_id="analyze-1",
            activity_id=activity_id,
            attempt=1,
        )

    tracker = GlobalBudgetTracker(
        GlobalBudgetPolicy(max_llm_calls=2),
        execution_identity=identity("activity-a"),
    )

    with pytest.raises(ValueError, match="different Graph execution identity"):
        tracker.for_execution_identity(identity("activity-b"))
