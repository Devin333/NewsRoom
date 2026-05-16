from __future__ import annotations

from core.framework.specs import EdgeCondition, StepStatus
from core.framework.workflow import DataBuffer, RoutingEngine, StepOutcome

from helpers import make_edge, make_step
from helpers import make_linear_workflow as _make_linear_workflow


def test_routing_contract_evaluates_core_conditions() -> None:
    workflow = type(_make_linear_workflow())(
        workflow_id="routing-contract",
        name="Routing Contract",
        version="1.0",
        start_step_id="gate",
        terminal_step_ids=["always", "success", "failure", "conditional"],
        steps=[
            make_step("gate"),
            make_step("always"),
            make_step("success"),
            make_step("failure"),
            make_step("conditional"),
        ],
        edges=[
            make_edge("gate", "always", condition=EdgeCondition.ALWAYS, priority=0),
            make_edge("gate", "success", condition=EdgeCondition.ON_SUCCESS, priority=1),
            make_edge("gate", "failure", condition=EdgeCondition.ON_FAILURE, priority=2),
            make_edge(
                "gate",
                "conditional",
                condition=EdgeCondition.CONDITIONAL,
                condition_expr='buffer["route"] == "conditional"',
                priority=3,
            ),
        ],
    )

    decision = RoutingEngine().decide(
        workflow,
        workflow.step_by_id("gate"),
        StepOutcome(status=StepStatus.SUCCEEDED),
        buffer=DataBuffer({"route": "conditional"}),
        fan_out=True,
    )

    evaluations = {item.edge_id: item.matched for item in decision.evaluations}
    assert decision.target_step_ids == ["always", "success", "conditional"]
    assert evaluations == {
        "gate-to-always": True,
        "gate-to-success": True,
        "gate-to-failure": False,
        "gate-to-conditional": True,
    }


def test_routing_contract_evaluates_governance_conditions_and_llm_hint() -> None:
    workflow = type(_make_linear_workflow())(
        workflow_id="routing-governance-contract",
        name="Routing Governance Contract",
        version="1.0",
        start_step_id="gate",
        terminal_step_ids=["quality", "human", "llm"],
        steps=[make_step("gate"), make_step("quality"), make_step("human"), make_step("llm")],
        edges=[
            make_edge("gate", "quality", condition=EdgeCondition.QUALITY_PASS, priority=0),
            make_edge("gate", "human", condition=EdgeCondition.HUMAN_REJECTED, priority=1),
            make_edge(
                "gate",
                "llm",
                condition=EdgeCondition.LLM_DECIDE,
                priority=2,
                metadata={"route_hint": "llm"},
            ),
        ],
    )

    decision = RoutingEngine().decide(
        workflow,
        workflow.step_by_id("gate"),
        StepOutcome(
            status=StepStatus.SUCCEEDED,
            outputs={
                "quality_gate_metrics": {"decision": "pass"},
                "human_review_decision": {"decision": "needs_changes"},
                "route": "llm",
            },
        ),
        buffer=DataBuffer(),
        fan_out=True,
    )

    assert decision.target_step_ids == ["quality", "human", "llm"]
    assert all(item.matched for item in decision.evaluations)
