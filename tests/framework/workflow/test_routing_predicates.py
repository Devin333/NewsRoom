from __future__ import annotations

from business.boards.cross_board.workflows.daily_intelligence.routing_predicates import (
    build_daily_intelligence_routing_predicate_registry,
)
from framework.specs import EdgeCondition, EdgeSpec, StepSpec, WorkflowSpec
from framework.workflow import DataBuffer
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


def test_business_predicates_route_verifier_rewrite_status() -> None:
    workflow = WorkflowSpec(
        workflow_id="wf",
        name="Workflow",
        version="1",
        start_step_id="verify",
        steps=[StepSpec("verify"), StepSpec("feedback"), StepSpec("publish")],
        edges=[
            EdgeSpec(
                "retry",
                "verify",
                "feedback",
                condition=EdgeCondition.VALIDATION_RETRY_REQUIRED,
            ),
            EdgeSpec(
                "pass",
                "verify",
                "publish",
                condition=EdgeCondition.VALIDATION_PASS,
            ),
        ],
    )
    outcome = StepOutcome.success(
        "verify",
        {"verification_result": {"status": "needs_rewrite"}},
    )

    decision = RoutingEngine(
        predicate_registry=build_daily_intelligence_routing_predicate_registry()
    ).decide(workflow, workflow.step_by_id("verify"), outcome)

    assert decision.target_step_id == "feedback"


def test_business_predicates_route_dotted_quality_gate_metrics_from_outcome() -> None:
    workflow = WorkflowSpec(
        workflow_id="wf",
        name="Workflow",
        version="1",
        start_step_id="quality",
        steps=[StepSpec("quality"), StepSpec("publish")],
        edges=[
            EdgeSpec("pass", "quality", "publish", condition=EdgeCondition.VALIDATION_PASS),
        ],
    )
    outcome = StepOutcome.success(
        "quality",
        {"quality.gate_metrics": {"decision": "pass"}},
    )

    decision = RoutingEngine(
        predicate_registry=build_daily_intelligence_routing_predicate_registry()
    ).decide(workflow, workflow.step_by_id("quality"), outcome)

    assert decision.target_step_id == "publish"


def test_business_predicates_route_dotted_report_quality_summary_from_buffer() -> None:
    workflow = WorkflowSpec(
        workflow_id="wf",
        name="Workflow",
        version="1",
        start_step_id="quality",
        steps=[StepSpec("quality"), StepSpec("rewrite")],
        edges=[
            EdgeSpec(
                "retry",
                "quality",
                "rewrite",
                condition=EdgeCondition.VALIDATION_RETRY_REQUIRED,
            ),
        ],
    )
    buffer = DataBuffer({"quality.report_summary": {"decision": "rewrite_required"}})

    decision = RoutingEngine(
        predicate_registry=build_daily_intelligence_routing_predicate_registry()
    ).decide(
        workflow,
        workflow.step_by_id("quality"),
        StepOutcome.success("quality", {}),
        buffer=buffer,
    )

    assert decision.target_step_id == "rewrite"


def test_business_predicates_keep_buffer_blocked_priority_with_dotted_keys() -> None:
    workflow = WorkflowSpec(
        workflow_id="wf",
        name="Workflow",
        version="1",
        start_step_id="quality",
        steps=[StepSpec("quality"), StepSpec("publish"), StepSpec("blocked")],
        edges=[
            EdgeSpec("blocked", "quality", "blocked", condition=EdgeCondition.VALIDATION_BLOCKED),
            EdgeSpec("pass", "quality", "publish", condition=EdgeCondition.VALIDATION_PASS),
        ],
    )
    buffer = DataBuffer({"quality.report_summary": {"decision": "blocked"}})
    outcome = StepOutcome.success(
        "quality",
        {"quality.gate_metrics": {"decision": "pass"}},
    )

    decision = RoutingEngine(
        predicate_registry=build_daily_intelligence_routing_predicate_registry()
    ).decide(workflow, workflow.step_by_id("quality"), outcome, buffer=buffer)

    assert decision.target_step_id == "blocked"


def test_business_predicates_route_agent_feedback_retry() -> None:
    workflow = WorkflowSpec(
        workflow_id="wf",
        name="Workflow",
        version="1",
        start_step_id="feedback",
        steps=[StepSpec("feedback"), StepSpec("writer"), StepSpec("finalize")],
        edges=[
            EdgeSpec(
                "retry",
                "feedback",
                "writer",
                condition=EdgeCondition.VALIDATION_RETRY_REQUIRED,
                priority=-10,
            ),
            EdgeSpec("finalize", "feedback", "finalize", priority=10),
        ],
    )
    outcome = StepOutcome.success(
        "feedback",
        {"agent_feedback_route": {"decision": "retry_required"}},
    )

    decision = RoutingEngine(
        predicate_registry=build_daily_intelligence_routing_predicate_registry()
    ).decide(workflow, workflow.step_by_id("feedback"), outcome)

    assert decision.target_step_id == "writer"
