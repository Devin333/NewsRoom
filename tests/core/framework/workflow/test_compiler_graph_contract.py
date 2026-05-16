from __future__ import annotations

from core.framework.specs import EdgeCondition
from core.framework.workflow import WorkflowCompileIssueCode, WorkflowCompiler

from helpers import make_edge, make_step
from helpers import make_linear_workflow as _make_linear_workflow


def test_compiler_contract_rejects_conditional_edge_without_expression() -> None:
    workflow = _make_linear_workflow(["decide", "publish"])
    workflow = type(workflow)(
        workflow_id=workflow.workflow_id,
        name=workflow.name,
        version=workflow.version,
        start_step_id=workflow.start_step_id,
        terminal_step_ids=workflow.terminal_step_ids,
        steps=workflow.steps,
        edges=[
            make_edge(
                "decide",
                "publish",
                edge_id="decide-publish",
                condition=EdgeCondition.CONDITIONAL,
            )
        ],
    )

    result = WorkflowCompiler().compile(workflow)

    assert result.passed is False
    assert result.has_error(WorkflowCompileIssueCode.CONDITIONAL_EDGE_MISSING_EXPR)


def test_compiler_contract_reports_unknown_edge_target() -> None:
    workflow = type(_make_linear_workflow())(
        workflow_id="compiler-contract-target",
        name="Compiler Contract Target",
        version="1.0",
        start_step_id="start",
        terminal_step_ids=["finish"],
        steps=[make_step("start"), make_step("finish")],
        edges=[make_edge("start", "missing")],
    )

    result = WorkflowCompiler().compile(workflow)

    assert result.passed is False
    assert result.has_error(WorkflowCompileIssueCode.UNKNOWN_EDGE_TARGET)
