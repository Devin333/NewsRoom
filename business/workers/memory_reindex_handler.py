from __future__ import annotations

from typing import Any

from business.workers._handler_utils import handler_output
from core.framework.workers.models import Task, TaskResult, TaskStatus


class MemoryReindexTaskHandler:
    task_type = "memory.reindex"

    def __init__(self, memory_service: Any | None = None) -> None:
        if memory_service is None:
            from interfaces.services.memory_service import MemoryApplicationService

            memory_service = MemoryApplicationService()
        self.memory_service = memory_service

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
            output=handler_output(result.to_dict()),
        )

