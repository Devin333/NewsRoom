from __future__ import annotations

from typing import Any

from business.layers.worker_output import (
    WorkerOutputEnvelope,
    report_status_from_output,
    report_summary_from_mapping,
    summary_fields,
    summary_from_output,
)
from framework.harness.control_plane.state import HarnessRunStatus
from framework.workers.models import TaskStatus


def optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def graph_status_value(status: Any) -> str:
    return str(getattr(status, "value", status))


def task_status_from_graph_status(status: str) -> TaskStatus:
    if status == HarnessRunStatus.SUCCEEDED.value:
        return TaskStatus.SUCCEEDED
    if status == HarnessRunStatus.BLOCKED.value:
        return TaskStatus.SUCCEEDED
    if status == HarnessRunStatus.WAITING_APPROVAL.value:
        return TaskStatus.WAITING_FOR_APPROVAL
    if status == HarnessRunStatus.HALTED.value:
        return TaskStatus.PAUSED
    if status == HarnessRunStatus.CANCELLED.value:
        return TaskStatus.CANCELLED
    return TaskStatus.FAILED


def report_status_from_result(result: Any) -> str | None:
    return report_status_from_output(getattr(result, "output", None))


def handler_output(payload: dict[str, Any], *, run_id: str | None = None) -> dict[str, Any]:
    return WorkerOutputEnvelope.from_payload(payload, run_id=run_id).to_dict()
