from __future__ import annotations

from core.framework.specs import WorkflowStatus
from interfaces.services.memory_service import MemoryApplicationService
from interfaces.services.run_service import RunApplicationService
from interfaces.services.source_service import SourceApplicationService
from core.framework.workers.models import Task, TaskResult, TaskStatus


class DailyIntelligenceTaskHandler:
    task_type = "daily_intelligence.run"

    def __init__(self, run_service: RunApplicationService | None = None) -> None:
        self.run_service = run_service or RunApplicationService()

    def handle(self, task: Task) -> TaskResult:
        result = self.run_service.run_daily(
            profile=task.payload.get("profile", "live-offline"),
            topic=task.payload.get("topic", "AI"),
            source_limit=int(task.payload.get("source_limit", 3)),
            run_id=task.payload.get("run_id"),
        )
        workflow_status = _workflow_status_value(result.status)
        task_status = _task_status_from_workflow_status(workflow_status)
        task_success = task_status != TaskStatus.FAILED
        workflow_error = result.error or {}
        return TaskResult(
            task_id=task.task_id,
            success=task_success,
            status=task_status,
            workflow_run_id=result.run_id,
            run_status=workflow_status,
            report_status=_report_status_from_result(result),
            output=_handler_output(result.to_dict()),
            error_type=workflow_error.get("error_type") if not task_success else None,
            error_message=workflow_error.get("message") if not task_success else None,
        )


class MemoryReindexTaskHandler:
    task_type = "memory.reindex"

    def __init__(self, memory_service: MemoryApplicationService | None = None) -> None:
        self.memory_service = memory_service or MemoryApplicationService()

    def handle(self, task: Task) -> TaskResult:
        run_id = str(task.payload.get("run_id") or "")
        if not run_id:
            raise ValueError("run_id is required")
        result = self.memory_service.reindex_run(
            run_id,
            topic=task.payload.get("topic"),
        )
        return TaskResult(
            task_id=task.task_id,
            success=True,
            status=TaskStatus.SUCCEEDED,
            workflow_run_id=run_id,
            run_status="succeeded",
            output=_handler_output(result.to_dict()),
        )


class SourceHealthCheckTaskHandler:
    task_type = "source_health_check"

    def __init__(self, source_service: SourceApplicationService | None = None) -> None:
        self.source_service = source_service or SourceApplicationService()

    def handle(self, task: Task) -> TaskResult:
        result = self.source_service.check_source_health(
            source_id=task.payload.get("source_id"),
            enabled_only=not bool(task.payload.get("include_disabled", False)),
            limit=_optional_int(task.payload.get("limit")),
            force=bool(task.payload.get("force", False)),
        )
        return TaskResult(
            task_id=task.task_id,
            success=True,
            status=TaskStatus.SUCCEEDED,
            run_status="succeeded",
            output=_handler_output(result.to_dict(), run_id=task.payload.get("run_id")),
        )


def _optional_int(value) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _workflow_status_value(status) -> str:
    return str(getattr(status, "value", status))


def _task_status_from_workflow_status(status: str) -> TaskStatus:
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


def _report_status_from_result(result) -> str | None:
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


def _handler_output(payload: dict, *, run_id: str | None = None) -> dict:
    output = dict(payload)
    actual_run_id = output.get("run_id") or run_id
    if actual_run_id is not None:
        output.setdefault("run_id", actual_run_id)
    output.setdefault("artifact_dir", output.get("artifact_dir"))
    output.setdefault("summary", _summary_from_output(output))
    return output


def _summary_from_output(output: dict) -> dict:
    nested_output = output.get("output")
    if isinstance(nested_output, dict):
        summary = nested_output.get("summary")
        if isinstance(summary, dict):
            return dict(summary)
        if isinstance(summary, str):
            return {"text": summary}
        nested_summary = _report_summary_from_mapping(nested_output)
        if nested_summary:
            return nested_summary
    return _report_summary_from_mapping(output)


def _report_summary_from_mapping(output: dict) -> dict:
    for key in ("report", "report_metadata", "blocked_report"):
        report = output.get(key)
        if isinstance(report, dict):
            return _summary_fields(report)
    return _summary_fields(output)


def _summary_fields(output: dict) -> dict:
    return {
        key: output[key]
        for key in ("title", "status", "report_status")
        if key in output
    }
