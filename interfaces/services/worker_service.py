from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.framework.workers import (
    DailyIntelligenceTaskHandler,
    RedisStreamTaskQueue,
    Task,
    TaskResult,
    TaskStatus,
)
from core.framework.workers.models import LeasedTask
from interfaces.services.run_service import RunApplicationService


DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/0"
DEFAULT_DAILY_QUEUE = "news:queue:daily"


@dataclass(frozen=True)
class EnqueuedTaskResult:
    task: Task
    message_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": str(self.message_id),
            "task_id": self.task.task_id,
            "task_type": self.task.task_type,
            "queue_name": self.task.queue_name,
            "status": self.task.status.value,
            "profile": self.task.payload.get("profile"),
            "topic": self.task.payload.get("topic"),
            "source_limit": self.task.payload.get("source_limit"),
            "run_id": self.task.payload.get("run_id"),
        }


@dataclass(frozen=True)
class WorkerRunOnceResult:
    processed: bool
    worker_id: str
    queue_name: str | None = None
    message_id: str | None = None
    task_id: str | None = None
    task_type: str | None = None
    success: bool | None = None
    task_status: TaskStatus | None = None
    workflow_run_id: str | None = None
    error_type: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "processed": self.processed,
            "worker_id": self.worker_id,
            "queue_name": self.queue_name,
            "message_id": self.message_id,
            "task_id": self.task_id,
            "task_type": self.task_type,
            "success": self.success,
            "task_status": self.task_status.value if self.task_status else None,
            "workflow_run_id": self.workflow_run_id,
            "error_type": self.error_type,
            "error_message": self.error_message,
        }


class WorkerApplicationService:
    def __init__(
        self,
        *,
        artifact_root: str | Path = ".newsroom/runs",
        redis_url: str | None = None,
        queue: RedisStreamTaskQueue | None = None,
        handlers: dict[str, DailyIntelligenceTaskHandler] | None = None,
    ) -> None:
        self.artifact_root = Path(artifact_root)
        self.queue = queue or RedisStreamTaskQueue(_redis_client_from_url(redis_url))
        if handlers is None:
            handlers = {
                DailyIntelligenceTaskHandler.task_type: DailyIntelligenceTaskHandler(
                    RunApplicationService(artifact_root=self.artifact_root)
                )
            }
        self.handlers = handlers

    def enqueue_daily(
        self,
        *,
        profile: str = "live-offline",
        topic: str = "AI",
        source_limit: int = 3,
        run_id: str | None = None,
        queue_name: str = DEFAULT_DAILY_QUEUE,
    ) -> EnqueuedTaskResult:
        payload: dict[str, Any] = {
            "profile": profile,
            "topic": topic,
            "source_limit": source_limit,
        }
        if run_id:
            payload["run_id"] = run_id
        _reject_secret_payload_keys(payload)
        task = Task(
            task_type=DailyIntelligenceTaskHandler.task_type,
            queue_name=queue_name,
            payload=payload,
        )
        message_id = self.queue.enqueue(task)
        return EnqueuedTaskResult(task=task, message_id=str(message_id))

    def run_once(
        self,
        *,
        worker_id: str,
        queue_names: list[str] | None = None,
        block_ms: int = 1000,
    ) -> WorkerRunOnceResult:
        queues = queue_names or [DEFAULT_DAILY_QUEUE]
        leased = self.queue.lease_one(worker_id, queues, block_ms=block_ms)
        if leased is None:
            return WorkerRunOnceResult(processed=False, worker_id=worker_id)

        result = self._handle_leased_task(leased)
        if result.success:
            self.queue.ack(leased.queue_name, leased.message_id)
        else:
            self._requeue_or_dead_letter(leased.task, result)
            self.queue.ack(leased.queue_name, leased.message_id)
        return WorkerRunOnceResult(
            processed=True,
            worker_id=worker_id,
            queue_name=leased.queue_name,
            message_id=leased.message_id,
            task_id=leased.task.task_id,
            task_type=leased.task.task_type,
            success=result.success,
            task_status=result.status,
            workflow_run_id=result.workflow_run_id,
            error_type=result.error_type,
            error_message=result.error_message,
        )

    def _handle_leased_task(self, leased: LeasedTask) -> TaskResult:
        handler = self.handlers.get(leased.task.task_type)
        if handler is None:
            return TaskResult(
                task_id=leased.task.task_id,
                success=False,
                status=TaskStatus.FAILED,
                error_type="UnknownTaskType",
                error_message=f"no handler for {leased.task.task_type}",
            )
        try:
            return handler.handle(leased.task)
        except Exception as exc:
            return TaskResult(
                task_id=leased.task.task_id,
                success=False,
                status=TaskStatus.FAILED,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

    def _requeue_or_dead_letter(self, task: Task, result: TaskResult) -> None:
        reason = result.error_message or result.error_type or "task failed"
        if task.attempts >= task.max_attempts:
            self.queue.move_to_dead_letter(task, reason)
            return
        task.status = TaskStatus.FAILED
        self.queue.enqueue(task)


def _redis_client_from_url(redis_url: str | None):
    import redis

    url = redis_url or os.environ.get("NEWS_REDIS_URL", DEFAULT_REDIS_URL)
    return redis.from_url(url, decode_responses=True)


def _reject_secret_payload_keys(payload: dict[str, Any]) -> None:
    secret_fragments = (
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "password",
        "secret",
        "token",
    )
    for key in payload:
        normalized = key.lower().replace("-", "_")
        if any(fragment in normalized for fragment in secret_fragments):
            raise ValueError(f"task payload key is not allowed: {key}")
