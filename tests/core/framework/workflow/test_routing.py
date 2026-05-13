import pytest

from core.framework.specs import EdgeCondition, EdgeSpec, StepSpec, StepStatus, WorkflowSpec
from core.framework.workflow import ConditionalExpressionError, DataBuffer, RoutingEngine, StepOutcome


def test_routing_engine_follows_true_conditional_edge() -> None:
    workflow = _routing_workflow(
        condition_expr='buffer["decision"] == "publish" and outcome.status == "succeeded"'
    )
    buffer = DataBuffer({"decision": "publish"})

    next_step = RoutingEngine().next_step(
        workflow,
        workflow.step_by_id("decide"),
        StepOutcome(status=StepStatus.SUCCEEDED, outputs={"route": "publish"}),
        buffer=buffer,
    )

    assert next_step == "publish"


def test_routing_engine_continues_after_false_conditional_edge() -> None:
    workflow = _routing_workflow(condition_expr='buffer["decision"] == "publish"')
    buffer = DataBuffer({"decision": "hold"})

    next_step = RoutingEngine().next_step(
        workflow,
        workflow.step_by_id("decide"),
        StepOutcome(status=StepStatus.SUCCEEDED),
        buffer=buffer,
    )

    assert next_step == "hold"


def test_routing_engine_returns_decision_metadata() -> None:
    workflow = _routing_workflow(condition_expr='buffer["decision"] == "publish"')
    buffer = DataBuffer({"decision": "hold"})

    decision = RoutingEngine().decide(
        workflow,
        workflow.step_by_id("decide"),
        StepOutcome(status=StepStatus.SUCCEEDED),
        buffer=buffer,
    )

    assert decision.target_step_id == "hold"
    assert [evaluation.edge_id for evaluation in decision.evaluations] == [
        "conditional-publish",
        "fallback-hold",
    ]
    assert [evaluation.matched for evaluation in decision.evaluations] == [False, True]
    assert decision.traversed_edge().edge_id == "fallback-hold"


def test_routing_engine_returns_multiple_next_steps_for_fan_out() -> None:
    workflow = WorkflowSpec(
        workflow_id="fan-out",
        name="Fan Out",
        version="1.0",
        start_step_id="start",
        steps=[
            StepSpec(step_id="start", implementation="sample.start"),
            StepSpec(step_id="left", implementation="sample.left"),
            StepSpec(step_id="right", implementation="sample.right"),
        ],
        edges=[
            EdgeSpec("start-left", "start", "left", condition=EdgeCondition.ALWAYS),
            EdgeSpec("start-right", "start", "right", condition=EdgeCondition.ALWAYS),
        ],
    )

    next_steps = RoutingEngine().next_steps(
        workflow,
        workflow.step_by_id("start"),
        StepOutcome(status=StepStatus.SUCCEEDED),
        buffer=DataBuffer(),
    )

    assert next_steps == ["left", "right"]


def test_routing_engine_supports_quality_human_and_budget_conditions() -> None:
    workflow = WorkflowSpec(
        workflow_id="target-conditions",
        name="Target Conditions",
        version="1.0",
        start_step_id="gate",
        steps=[
            StepSpec(
                step_id="gate",
                implementation="sample.gate",
                write_keys=["quality_gate_metrics"],
            ),
            StepSpec(step_id="rewrite", implementation="sample.rewrite"),
            StepSpec(step_id="approved", implementation="sample.approved"),
            StepSpec(step_id="budget", implementation="sample.budget"),
        ],
        edges=[
            EdgeSpec(
                "gate-rewrite",
                "gate",
                "rewrite",
                condition=EdgeCondition.QUALITY_REWRITE_REQUIRED,
                priority=0,
            ),
            EdgeSpec(
                "gate-approved",
                "gate",
                "approved",
                condition=EdgeCondition.HUMAN_APPROVED,
                priority=1,
            ),
            EdgeSpec(
                "gate-budget",
                "gate",
                "budget",
                condition=EdgeCondition.BUDGET_EXCEEDED,
                priority=2,
            ),
        ],
    )
    buffer = DataBuffer(
        {
            "quality_gate_metrics": {"decision": "rewrite_required"},
            "human_review_decision": {"decision": "approved"},
            "budget_exceeded": True,
        }
    )

    next_steps = RoutingEngine().next_steps(
        workflow,
        workflow.step_by_id("gate"),
        StepOutcome(status=StepStatus.SUCCEEDED),
        buffer=buffer,
    )

    assert next_steps == ["rewrite", "approved", "budget"]


def test_routing_engine_blocks_unsafe_function_calls() -> None:
    workflow = _routing_workflow(condition_expr='__import__("os").system("echo unsafe")')

    with pytest.raises(ConditionalExpressionError, match="Call"):
        RoutingEngine().next_step(
            workflow,
            workflow.step_by_id("decide"),
            StepOutcome(status=StepStatus.SUCCEEDED),
            buffer=DataBuffer({"decision": "publish"}),
        )


def _routing_workflow(condition_expr: str) -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="routing",
        name="Routing",
        version="1.0",
        start_step_id="decide",
        steps=[
            StepSpec(step_id="decide", implementation="sample.decide"),
            StepSpec(step_id="publish", implementation="sample.publish"),
            StepSpec(step_id="hold", implementation="sample.hold"),
        ],
        edges=[
            EdgeSpec(
                edge_id="conditional-publish",
                source_step_id="decide",
                target_step_id="publish",
                condition=EdgeCondition.CONDITIONAL,
                condition_expr=condition_expr,
                priority=0,
            ),
            EdgeSpec(
                edge_id="fallback-hold",
                source_step_id="decide",
                target_step_id="hold",
                condition=EdgeCondition.ALWAYS,
                priority=1,
            ),
        ],
    )
