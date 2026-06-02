from __future__ import annotations

from typing import Any

from business.layers.worker_output import (
    WorkerOutputEnvelope,
    report_status_from_output,
    report_summary_from_mapping,
    summary_fields,
    summary_from_output,
)
from framework.specs import WorkflowStatus
from framework.workers.models import TaskStatus


def optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def workflow_status_value(status: Any) -> str:
    return str(getattr(status, "value", status))


def task_status_from_workflow_status(status: str) -> TaskStatus:
    if status == WorkflowStatus.SUCCEEDED.value:
        return TaskStatus.SUCCEEDED
    if status in {WorkflowStatus.BLOCKED.value, WorkflowStatus.BUDGET_EXCEEDED.value}:
        return TaskStatus.SUCCEEDED
    if status == WorkflowStatus.WAITING_FOR_HUMAN.value:
        return TaskStatus.WAITING_FOR_APPROVAL
    if status == WorkflowStatus.PAUSED.value:
        return TaskStatus.PAUSED
    if status == WorkflowStatus.CANCELLED.value:
        return TaskStatus.CANCELLED
    return TaskStatus.FAILED


def report_status_from_result(result: Any) -> str | None:
    return report_status_from_output(getattr(result, "output", None))


def handler_output(payload: dict[str, Any], *, run_id: str | None = None) -> dict[str, Any]:
    return WorkerOutputEnvelope.from_payload(payload, run_id=run_id).to_dict()
