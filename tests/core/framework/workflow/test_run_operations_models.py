from __future__ import annotations

from core.framework.workflow.operations import (
    OperationActor,
    OperationResult,
    WorkflowOperationStatus,
    WorkflowOperationType,
)


def test_operations_module_imports_independently() -> None:
    result = OperationResult(
        operation_id="op_1",
        operation_type=WorkflowOperationType.CANCEL_RUN,
        status=WorkflowOperationStatus.ACCEPTED,
        run_id="run-1",
        message="accepted",
    )

    assert result.operation_type == WorkflowOperationType.CANCEL_RUN
    assert result.status == WorkflowOperationStatus.ACCEPTED


def test_operation_result_expresses_all_statuses() -> None:
    statuses = {
        OperationResult(
            operation_id=f"op_{status.value}",
            operation_type=WorkflowOperationType.RESUME_WITH_PATCH,
            status=status,
            run_id="run-1",
            message=status.value,
        ).status
        for status in WorkflowOperationStatus
    }

    assert statuses == set(WorkflowOperationStatus)


def test_each_operation_has_stable_operation_type() -> None:
    assert {operation.value for operation in WorkflowOperationType} == {
        "cancel_run",
        "rerun_from_step",
        "resume_with_patch",
        "skip_step",
        "mark_blocked_resolved",
    }


def test_operation_actor_shape_is_reserved() -> None:
    actor = OperationActor(
        actor_id="devin",
        actor_type="service",
        metadata={"ip": "127.0.0.1"},
    )

    assert actor.to_dict() == {
        "actor_id": "devin",
        "actor_type": "service",
        "metadata": {"ip": "127.0.0.1"},
    }
