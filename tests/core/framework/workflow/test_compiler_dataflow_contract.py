from __future__ import annotations

from core.framework.workflow import WorkflowCompileIssueCode, WorkflowCompiler

from helpers import make_step
from helpers import make_linear_workflow as _make_linear_workflow


def test_compiler_contract_rejects_read_key_not_from_request_or_upstream() -> None:
    workflow = type(_make_linear_workflow())(
        workflow_id="compiler-contract-dataflow",
        name="Compiler Contract Dataflow",
        version="1.0",
        start_step_id="finish",
        terminal_step_ids=["finish"],
        steps=[make_step("finish", read_keys=["missing"], write_keys=["report"])],
    )

    result = WorkflowCompiler().compile(workflow)

    assert result.passed is False
    assert result.has_error(WorkflowCompileIssueCode.READ_KEY_UNAVAILABLE)


def test_compiler_contract_allows_request_and_upstream_keys() -> None:
    workflow = _make_linear_workflow(["plan", "write"])

    result = WorkflowCompiler().compile(workflow)

    assert result.passed is True
    assert result.read_write_plan.step_plans["plan"].read_keys == {"request"}
    assert result.read_write_plan.step_plans["write"].upstream_write_keys == {"plan_output"}
