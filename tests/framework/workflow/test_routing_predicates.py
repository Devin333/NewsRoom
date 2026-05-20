from __future__ import annotations

from business.boards.cross_board.workflows.daily_intelligence.routing_predicates import (
    build_daily_intelligence_routing_predicate_registry,
)
from framework.specs import EdgeCondition, EdgeSpec, StepSpec, WorkflowSpec
from framework.workflow.routing import RoutingEngine
from framework.workflow.runtime.result import StepOutcome


def test_routing_engine_uses_generic_builtin_predicates() -> None:
    workflow = WorkflowSpec(
        workflow_id="wf",
        name="Workflow",
        version="1",
        start_step_id="start",
        steps=[StepSpec("start"), StepSpec("done")],
        edges=[EdgeSpec("e1", "start", "done", condition=EdgeCondition.ON_SUCCESS)],
    )

    decision = RoutingEngine().decide(
        workflow,
        workflow.step_by_id("start"),
        StepOutcome.success("start", {"ok": True}),
    )

    assert decision.target_step_id == "done"


def test_business_predicates_can_handle_legacy_quality_conditions() -> None:
    workflow = WorkflowSpec(
        workflow_id="wf",
        name="Workflow",
        version="1",
        start_step_id="review",
        steps=[StepSpec("review"), StepSpec("publish")],
        edges=[
            EdgeSpec("e1", "review", "publish", condition=EdgeCondition.VALIDATION_PASS),
        ],
    )
    outcome = StepOutcome.success("review", {"editor_review": {"decision": "pass"}})

    default_decision = RoutingEngine().decide(workflow, workflow.step_by_id("review"), outcome)
    business_decision = RoutingEngine(
        predicate_registry=build_daily_intelligence_routing_predicate_registry()
    ).decide(workflow, workflow.step_by_id("review"), outcome)

    assert default_decision.target_step_id is None
    assert business_decision.target_step_id == "publish"
