import pytest

from core.framework.specs import (
    StepSpec,
    StepStatus,
    StepType,
    WorkflowStatus,
)
from core.framework.workflow import StepOutcome, WorkflowError, WorkflowResult
from core.framework.workers import TaskStatus


def test_workflow_contract_enums_cover_target_values() -> None:
    assert {status.value for status in WorkflowStatus} >= {
        "created",
        "running",
        "paused",
        "waiting_for_human",
        "retrying",
        "succeeded",
        "failed",
        "blocked",
        "cancelled",
        "budget_exceeded",
    }
    assert {status.value for status in StepStatus} >= {
        "pending",
        "running",
        "succeeded",
        "failed",
        "blocked",
        "paused",
        "timeout",
        "skipped",
    }
    assert {step_type.value for step_type in StepType} >= {
        "function",
        "agent_loop",
        "router",
        "quality_gate",
        "persist",
        "artifact",
        "parallel_group",
        "join",
        "subworkflow",
        "human_review",
        "notification",
        "tool_batch",
    }


def test_invalid_status_cannot_deserialize() -> None:
    with pytest.raises(ValueError):
        StepOutcome.from_dict({"status": "queued"})

    with pytest.raises(ValueError):
        WorkflowResult.from_dict(
            {
                "run_id": "run-1",
                "workflow_id": "wf",
                "workflow_version": "1.0",
                "status": "dead_letter",
            }
        )


def test_workflow_status_and_task_status_are_not_interchangeable() -> None:
    assert TaskStatus.QUEUED.value not in {status.value for status in WorkflowStatus}
    assert WorkflowStatus.WAITING_FOR_HUMAN.value not in {status.value for status in TaskStatus}

    with pytest.raises(ValueError):
        WorkflowResult(
            run_id="run-1",
            workflow_id="wf",
            workflow_version="1.0",
            status=TaskStatus.QUEUED.value,
            error=WorkflowError("TaskStatusMixedIntoWorkflow", "bad status"),
        )


def test_step_type_deserialization_rejects_unknown_values() -> None:
    with pytest.raises(ValueError):
        StepSpec(step_id="bad", implementation="bad.impl", step_type="worker_task")
