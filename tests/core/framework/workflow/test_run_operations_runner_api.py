from __future__ import annotations

from core.framework.runner import WorkflowRunner
from core.framework.workflow.operations import (
    OperationResult,
    WorkflowOperationStatus,
    WorkflowOperationType,
)
from core.framework.workflow.step_runner import FunctionStepRegistry


class _OperationService:
    def cancel_run(self, run_id, reason, *, actor=None):
        return _result(WorkflowOperationType.CANCEL_RUN, run_id)

    def rerun_from_step(self, run_id, step_id, *, actor=None):
        return _result(WorkflowOperationType.RERUN_FROM_STEP, run_id, new_run_id="new-run")

    def resume_with_patch(self, run_id, patch, *, actor=None):
        return _result(WorkflowOperationType.RESUME_WITH_PATCH, run_id, new_run_id="new-run")

    def skip_step(self, run_id, step_id, reason, *, actor=None):
        return _result(WorkflowOperationType.SKIP_STEP, run_id, new_run_id="new-run")

    def mark_blocked_resolved(self, run_id, resolution, *, actor=None):
        return _result(WorkflowOperationType.MARK_BLOCKED_RESOLVED, run_id)


def test_workflow_runner_exposes_operation_api(tmp_path) -> None:
    runner = WorkflowRunner(
        artifact_root=tmp_path,
        function_registry=FunctionStepRegistry(),
        operation_service=_OperationService(),
    )

    assert runner.cancel_run("run-1", "stop").operation_type == WorkflowOperationType.CANCEL_RUN
    assert (
        runner.rerun_from_step("run-1", "step").operation_type
        == WorkflowOperationType.RERUN_FROM_STEP
    )
    assert (
        runner.resume_with_patch("run-1", {}).operation_type
        == WorkflowOperationType.RESUME_WITH_PATCH
    )
    assert runner.skip_step("run-1", "step", "skip").operation_type == WorkflowOperationType.SKIP_STEP
    assert (
        runner.mark_blocked_resolved("run-1", {"reason": "fixed"}).operation_type
        == WorkflowOperationType.MARK_BLOCKED_RESOLVED
    )


def test_operation_result_does_not_expose_internal_paths() -> None:
    payload = _result(
        WorkflowOperationType.CANCEL_RUN,
        "run-1",
        details={"cancel_marker": "cancel.json"},
    ).to_dict()

    assert "artifact_root" not in payload["details"]
    assert "cancel.json" == payload["details"]["cancel_marker"]


def _result(
    operation_type: WorkflowOperationType,
    run_id: str,
    *,
    new_run_id: str | None = None,
    details: dict | None = None,
) -> OperationResult:
    return OperationResult(
        operation_id="op_1",
        operation_type=operation_type,
        status=WorkflowOperationStatus.APPLIED,
        run_id=run_id,
        message="ok",
        new_run_id=new_run_id,
        details=details or {},
    )
