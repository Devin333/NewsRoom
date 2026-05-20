from __future__ import annotations

from typing import Any

from business.layers._worker_utils import (
    handler_output,
    report_status_from_result,
    task_status_from_workflow_status,
    workflow_status_value,
)
from core.framework.workers.models import Task, TaskResult, TaskStatus


class DailyIntelligenceTaskHandler:
    task_type = "daily_intelligence.run"

    def __init__(self, run_service: Any) -> None:
        self.run_service = run_service

    def handle(self, task: Task) -> TaskResult:
        result = self.run_service.run_daily(
            profile=task.payload.get("profile", "live-offline"),
            topic=task.payload.get("topic", "AI"),
            source_limit=int(task.payload.get("source_limit", 3)),
            run_id=task.payload.get("run_id"),
        )
        workflow_status = workflow_status_value(result.status)
        task_status = task_status_from_workflow_status(workflow_status)
        task_success = task_status != TaskStatus.FAILED
        workflow_error = result.error or {}
        return TaskResult(
            task_id=task.task_id,
            success=task_success,
            status=task_status,
            workflow_run_id=result.run_id,
            run_status=workflow_status,
            report_status=report_status_from_result(result),
            output=handler_output(result.to_dict()),
            error_type=workflow_error.get("error_type") if not task_success else None,
            error_message=workflow_error.get("message") if not task_success else None,
        )
