from __future__ import annotations

from typing import Any

from business.workers._handler_utils import handler_output, optional_int
from core.framework.workers.models import Task, TaskResult, TaskStatus


class SourceHealthCheckTaskHandler:
    task_type = "source_health_check"

    def __init__(self, source_service: Any | None = None) -> None:
        if source_service is None:
            from interfaces.services.source_service import SourceApplicationService

            source_service = SourceApplicationService()
        self.source_service = source_service

    def handle(self, task: Task) -> TaskResult:
        result = self.source_service.check_source_health(
            source_id=task.payload.get("source_id"),
            enabled_only=not bool(task.payload.get("include_disabled", False)),
            limit=optional_int(task.payload.get("limit")),
            force=bool(task.payload.get("force", False)),
        )
        return TaskResult(
            task_id=task.task_id,
            success=True,
            status=TaskStatus.SUCCEEDED,
            run_status="succeeded",
            output=handler_output(result.to_dict(), run_id=task.payload.get("run_id")),
        )

