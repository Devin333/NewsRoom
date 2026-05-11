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
