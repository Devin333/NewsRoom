from __future__ import annotations

from core.framework.specs import EdgeCondition, EdgeSpec, StepSpec, StepStatus, WorkflowSpec
from core.framework.workflow import DataBuffer, RoutingEngine, StepOutcome


def test_human_review_approved_routes_human_approved() -> None:
    workflow = _workflow()

    next_steps = RoutingEngine().next_steps(
        workflow,
        workflow.step_by_id("review"),
        StepOutcome(
            status=StepStatus.SUCCEEDED,
            outputs={"human_review_decision": {"decision": "approved"}},
            next_hint="human_approved",
        ),
        buffer=DataBuffer(),
    )

    assert next_steps == ["publish"]


def test_human_review_rejected_routes_human_rejected() -> None:
    workflow = _workflow()

    next_steps = RoutingEngine().next_steps(
        workflow,
        workflow.step_by_id("review"),
        StepOutcome(
            status=StepStatus.SUCCEEDED,
            outputs={"human_review_decision": {"decision": "rejected"}},
            next_hint="human_rejected",
        ),
        buffer=DataBuffer(),
    )

    assert next_steps == ["blocked"]


def test_human_review_needs_changes_can_route_conditional() -> None:
    workflow = _workflow()

    next_steps = RoutingEngine().next_steps(
        workflow,
        workflow.step_by_id("review"),
        StepOutcome(
            status=StepStatus.SUCCEEDED,
            outputs={"human_review_decision": {"decision": "needs_changes"}},
            next_hint="human_needs_changes",
        ),
        buffer=DataBuffer(),
    )

    assert next_steps == ["rewrite", "blocked"]


def _workflow() -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="human-routes",
        name="Human Routes",
        version="1.0",
        start_step_id="review",
        steps=[
            StepSpec(
                "review",
                "human.review",
                step_type="human_review",
                write_keys=["human_review_decision"],
            ),
            StepSpec("publish", "sample.publish"),
            StepSpec("blocked", "sample.blocked"),
            StepSpec("rewrite", "sample.rewrite"),
        ],
        edges=[
            EdgeSpec("approved", "review", "publish", condition=EdgeCondition.HUMAN_APPROVED),
            EdgeSpec("rejected", "review", "blocked", condition=EdgeCondition.HUMAN_REJECTED),
            EdgeSpec(
                "needs-changes",
                "review",
                "rewrite",
                condition=EdgeCondition.CONDITIONAL,
                condition_expr='outcome["outputs"]["human_review_decision"]["decision"] == "needs_changes"',
                priority=-1,
            ),
        ],
    )
