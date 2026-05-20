from __future__ import annotations

from typing import Any

from core.framework.specs import WorkflowStatus
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
    output = getattr(result, "output", None)
    if isinstance(output, dict):
        report = output.get("report") or output.get("report_metadata")
        if isinstance(report, dict):
            status = report.get("status") or report.get("report_status")
            if status is not None:
                return str(status)
        if "blocked_report" in output:
            return "blocked"
    return None


def handler_output(payload: dict[str, Any], *, run_id: str | None = None) -> dict[str, Any]:
    output = dict(payload)
    actual_run_id = output.get("run_id") or run_id
    if actual_run_id is not None:
        output.setdefault("run_id", actual_run_id)
    output.setdefault("artifact_dir", output.get("artifact_dir"))
    output.setdefault("summary", summary_from_output(output))
    return output


def summary_from_output(output: dict[str, Any]) -> dict[str, Any]:
    nested_output = output.get("output")
    if isinstance(nested_output, dict):
        summary = nested_output.get("summary")
        if isinstance(summary, dict):
            return dict(summary)
        if isinstance(summary, str):
            return {"text": summary}
        nested_summary = report_summary_from_mapping(nested_output)
        if nested_summary:
            return nested_summary
    return report_summary_from_mapping(output)


def report_summary_from_mapping(output: dict[str, Any]) -> dict[str, Any]:
    for key in ("report", "report_metadata", "blocked_report"):
        report = output.get(key)
        if isinstance(report, dict):
            return summary_fields(report)
    return summary_fields(output)


def summary_fields(output: dict[str, Any]) -> dict[str, Any]:
    return {
        key: output[key]
        for key in ("title", "status", "report_status")
        if key in output
    }
