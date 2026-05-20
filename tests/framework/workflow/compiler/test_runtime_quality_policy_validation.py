from __future__ import annotations

from framework.specs import StepSpec, WorkflowPolicySpec, WorkflowSpec
from framework.workflow.compiler import WorkflowCompileIssueCode, WorkflowCompiler


def _workflow(*, step: StepSpec, policies: WorkflowPolicySpec | None = None) -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="wf",
        name="Workflow",
        version="1.0",
        steps=[step],
        terminal_step_ids=[step.step_id],
        policies=policies,
    )


def test_compiler_rejects_invalid_trace_level() -> None:
    workflow = _workflow(
        step=StepSpec(step_id="s1"),
        policies=WorkflowPolicySpec(runtime_quality={"trace": {"level": "verbose"}}),
    )

    result = WorkflowCompiler().compile(workflow)

    assert result.has_error(WorkflowCompileIssueCode.RUNTIME_QUALITY_POLICY_INVALID)


def test_compiler_rejects_invalid_gate_mode_and_dimension() -> None:
    workflow = _workflow(
        step=StepSpec(
            step_id="s1",
            runtime_quality={
                "gate": {
                    "mode": "strict",
                    "dimensions": ["report_quality"],
                }
            },
        )
    )

    result = WorkflowCompiler().compile(workflow)

    assert result.has_error(WorkflowCompileIssueCode.RUNTIME_QUALITY_POLICY_INVALID)
    assert len(result.errors) >= 2


def test_compiler_rejects_non_positive_trace_payload_limit() -> None:
    workflow = _workflow(
        step=StepSpec(step_id="s1"),
        policies=WorkflowPolicySpec(runtime_quality={"trace": {"max_payload_bytes": 0}}),
    )

    result = WorkflowCompiler().compile(workflow)

    assert result.has_error(WorkflowCompileIssueCode.RUNTIME_QUALITY_POLICY_INVALID)


def test_compiler_rejects_step_eval_required_outputs_not_declared() -> None:
    workflow = _workflow(
        step=StepSpec(
            step_id="s1",
            write_keys=["ok"],
            runtime_quality={
                "evaluation": {
                    "enabled": True,
                    "required_output_keys": ["missing"],
                }
            },
        )
    )

    result = WorkflowCompiler().compile(workflow)

    assert result.has_error(WorkflowCompileIssueCode.RUNTIME_QUALITY_POLICY_INVALID)
