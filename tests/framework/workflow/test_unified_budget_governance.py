from __future__ import annotations

import pytest

from framework.governance.budget import BudgetScopeType
from framework.llm.budget import GlobalBudgetPolicy, GlobalBudgetTracker
from framework.llm.models import TokenUsage
from framework.workflow.governance.budget import (
    WorkflowBudgetPolicy,
    WorkflowBudgetTracker,
    restore_global_budget_tracker_usage,
)


def test_workflow_keeps_tool_and_wall_time_ownership_over_canonical_llm_view() -> None:
    policy = WorkflowBudgetPolicy(
        max_total_tokens=50,
        max_llm_calls=2,
        max_tool_calls=1,
    )
    global_tracker = GlobalBudgetTracker(
        policy.to_global_budget_policy(),
        run_id="run-workflow-budget",
    )
    workflow_tracker = WorkflowBudgetTracker(
        policy,
        global_budget_tracker=global_tracker,
    )

    llm_check = workflow_tracker.record_llm_usage(
        input_tokens=6,
        output_tokens=4,
    )
    tool_check = workflow_tracker.record_tool_call()
    exceeded = workflow_tracker.record_tool_call()

    assert llm_check.exceeded is False
    assert tool_check.exceeded is False
    assert exceeded.exceeded is True
    assert exceeded.exceeded_reason == "max_tool_calls"
    assert exceeded.usage.llm_calls == 1
    assert exceeded.usage.total_tokens == 10
    assert global_tracker.usage.llm_calls == 1


def test_workflow_checkpoint_restore_uses_public_canonical_contract() -> None:
    policy = WorkflowBudgetPolicy(max_total_tokens=50, max_llm_calls=2)
    source = WorkflowBudgetTracker(
        policy,
        global_budget_tracker=GlobalBudgetTracker(
            policy.to_global_budget_policy(),
            run_id="run-checkpoint-source",
        ),
    )
    source.record_llm_usage(input_tokens=5, output_tokens=2)
    snapshot = source.global_budget_tracker.canonical_snapshot()
    target = GlobalBudgetTracker(
        policy.to_global_budget_policy(),
        run_id="run-checkpoint-target",
    )

    assert restore_global_budget_tracker_usage(target, snapshot) is True
    assert target.canonical_snapshot() == snapshot
    assert WorkflowBudgetTracker(
        policy,
        global_budget_tracker=target,
    ).usage().total_tokens == 7


def test_sibling_workflow_subagent_views_do_not_expose_reservation_history() -> None:
    root = GlobalBudgetTracker(GlobalBudgetPolicy(max_llm_calls=2), run_id="run-privacy")
    workflow = root.child_tracker("workflow", scope_type=BudgetScopeType.WORKFLOW)
    subagent = root.child_tracker("subagent", scope_type=BudgetScopeType.SUBAGENT)
    operation = workflow.reserve_direct_operation(
        operation_id="workflow-operation",
        idempotency_key="workflow-idempotency",
        input_tokens=1,
        output_tokens=0,
    )

    assert operation.operation_id == "workflow-operation"
    assert subagent.usage.llm_calls == 0
    assert root.usage.llm_calls == 1
    with pytest.raises(ValueError):
        workflow.restore(root.canonical_snapshot())
