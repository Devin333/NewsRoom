from __future__ import annotations

from interfaces.services.memory_service import MemoryApplicationService
from interfaces.services.run_service import RunApplicationService
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
        return TaskResult(
            task_id=task.task_id,
            success=result.status.value == "succeeded",
            status=TaskStatus.SUCCEEDED if result.status.value == "succeeded" else TaskStatus.FAILED,
            workflow_run_id=result.run_id,
            output=result.to_dict(),
            error_type=(result.error or {}).get("error_type") if result.error else None,
            error_message=(result.error or {}).get("message") if result.error else None,
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
            output=result.to_dict(),
        )
