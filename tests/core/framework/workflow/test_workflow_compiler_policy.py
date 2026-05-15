from __future__ import annotations

import pytest

from core.framework.specs import EdgeCondition, EdgeSpec, StepSpec, WorkflowSpec
from core.framework.workflow import WorkflowCompileIssueCode, WorkflowCompiler


def test_compile_fails_when_conditional_edge_has_no_expression() -> None:
    result = WorkflowCompiler().compile(
        _policy_spec(
            EdgeSpec(
                "start-finish",
                "start",
                "finish",
                condition=EdgeCondition.CONDITIONAL,
            )
        )
    )

    assert result.passed is False
    assert result.has_error(WorkflowCompileIssueCode.CONDITIONAL_EDGE_MISSING_EXPR)


def test_compile_allows_conditional_edge_with_expression() -> None:
    result = WorkflowCompiler().compile(
        _policy_spec(
            EdgeSpec(
                "start-finish",
                "start",
                "finish",
                condition=EdgeCondition.CONDITIONAL,
                condition_expr='buffer["route"] == "finish"',
            )
        )
    )

    assert result.passed is True


def test_compile_allows_llm_decide_for_regular_routing() -> None:
    result = WorkflowCompiler().compile(
        _policy_spec(
            EdgeSpec(
                "llm-route",
                "start",
                "finish",
                condition=EdgeCondition.LLM_DECIDE,
                metadata={"decision_category": "routing"},
            )
        )
    )

    assert result.passed is True


@pytest.mark.parametrize("category", ["publish", "approval", "quality_pass", "safety"])
def test_compile_rejects_llm_decide_for_governance_decisions(category: str) -> None:
    result = WorkflowCompiler().compile(
        _policy_spec(
            EdgeSpec(
                f"llm-{category}",
                "start",
                "finish",
                condition=EdgeCondition.LLM_DECIDE,
                metadata={"decision_category": category},
            )
        )
    )

    assert result.passed is False
    assert result.has_error(WorkflowCompileIssueCode.LLM_DECIDE_FOR_GOVERNANCE)


def test_compile_rejects_llm_decide_for_governance_purpose() -> None:
    result = WorkflowCompiler().compile(
        _policy_spec(
            EdgeSpec(
                "llm-approval",
                "start",
                "finish",
                condition=EdgeCondition.LLM_DECIDE,
                metadata={"purpose": "approval"},
            )
        )
    )

    assert result.passed is False
    assert result.has_error(WorkflowCompileIssueCode.LLM_DECIDE_FOR_GOVERNANCE)


def _policy_spec(edge: EdgeSpec) -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="compiler-policy",
        name="Compiler Policy",
        version="1.0",
        start_step_id="start",
        terminal_step_ids=["finish"],
        steps=[
            StepSpec("start", "sample.start", write_keys=["route"]),
            StepSpec("finish", "sample.finish", read_keys=["route"], write_keys=["report"]),
        ],
        edges=[edge],
    )
