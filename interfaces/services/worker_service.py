from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.framework.workers import (
    DailyIntelligenceTaskHandler,
    MemoryReindexTaskHandler,
    RedisStreamTaskQueue,
    RedisWorkerRegistry,
    Task,
    TaskResult,
    TaskStatus,
    WorkerHeartbeat,
    WorkerHeartbeatStatus,
    WorkerStatus,
)
from core.framework.workers.models import LeasedTask
from interfaces.services.run_service import RunApplicationService


DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/0"
DEFAULT_DAILY_QUEUE = "news:queue:daily"
DEFAULT_MEMORY_QUEUE = "news:queue:memory"


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


@dataclass(frozen=True)
class WorkerHeartbeatResult:
    worker: WorkerHeartbeatStatus

    def to_dict(self) -> dict[str, Any]:
        return {"worker": self.worker.to_dict()}


@dataclass(frozen=True)
class WorkerStatusResult:
    workers: list[WorkerHeartbeatStatus]
    stale_after_seconds: int
    worker_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        worker_payloads = [worker.to_dict() for worker in self.workers]
        return {
            "worker_id": self.worker_id,
            "worker_count": len(worker_payloads),
            "unhealthy_count": sum(1 for worker in self.workers if worker.status == WorkerStatus.UNHEALTHY),
            "stale_after_seconds": self.stale_after_seconds,
            "workers": worker_payloads,
        }


class WorkerApplicationService:
    def __init__(
        self,
        *,
        artifact_root: str | Path = ".newsroom/runs",
        redis_url: str | None = None,
        queue: RedisStreamTaskQueue | None = None,
        worker_registry: RedisWorkerRegistry | None = None,
        handlers: dict[str, DailyIntelligenceTaskHandler] | None = None,
    ) -> None:
        self.artifact_root = Path(artifact_root)
        redis_client = None
        if queue is None:
            redis_client = _redis_client_from_url(redis_url)
        self.queue = queue or RedisStreamTaskQueue(redis_client)
        self.worker_registry = worker_registry
        if self.worker_registry is None and queue is None:
            self.worker_registry = RedisWorkerRegistry(redis_client)
        if handlers is None:
            handlers = {
                DailyIntelligenceTaskHandler.task_type: DailyIntelligenceTaskHandler(
                    RunApplicationService(artifact_root=self.artifact_root)
                ),
                MemoryReindexTaskHandler.task_type: MemoryReindexTaskHandler(),
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

    def enqueue_memory_reindex(
        self,
        *,
        run_id: str,
        topic: str | None = None,
        queue_name: str = DEFAULT_MEMORY_QUEUE,
    ) -> EnqueuedTaskResult:
        payload: dict[str, Any] = {"run_id": run_id}
        if topic:
            payload["topic"] = topic
        _reject_secret_payload_keys(payload)
        task = Task(
            task_type=MemoryReindexTaskHandler.task_type,
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
        self._record_worker_heartbeat(
            worker_id=worker_id,
            queue_names=queues,
            status=WorkerStatus.RUNNING,
        )
        leased = self.queue.lease_one(worker_id, queues, block_ms=block_ms)
        if leased is None:
            self._record_worker_heartbeat(
                worker_id=worker_id,
                queue_names=queues,
                status=WorkerStatus.RUNNING,
            )
            return WorkerRunOnceResult(processed=False, worker_id=worker_id)

        self._record_worker_heartbeat(
            worker_id=worker_id,
            queue_names=queues,
            status=WorkerStatus.RUNNING,
            current_task_id=leased.task.task_id,
        )
        result = self._handle_leased_task(leased)
        if result.success:
            self.queue.ack(leased.queue_name, leased.message_id)
        else:
            self._requeue_or_dead_letter(leased.task, result)
            self.queue.ack(leased.queue_name, leased.message_id)
        self._record_worker_heartbeat(
            worker_id=worker_id,
            queue_names=queues,
            status=WorkerStatus.RUNNING,
            processed_increment=1 if result.success else 0,
            failed_increment=0 if result.success else 1,
        )
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

    def record_heartbeat(
        self,
        *,
        worker_id: str,
        queue_names: list[str] | None = None,
        status: WorkerStatus | str = WorkerStatus.RUNNING,
        current_task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> WorkerHeartbeatResult:
        worker = self._record_worker_heartbeat(
            worker_id=worker_id,
            queue_names=queue_names or [DEFAULT_DAILY_QUEUE],
            status=status,
            current_task_id=current_task_id,
            metadata=metadata,
            now=now,
        )
        return WorkerHeartbeatResult(
            worker=WorkerHeartbeatStatus.from_record(
                worker,
                now=now,
                stale_after_seconds=60,
            )
        )

    def list_worker_status(
        self,
        *,
        worker_id: str | None = None,
        stale_after_seconds: int = 60,
        now: datetime | None = None,
    ) -> WorkerStatusResult:
        registry = self._require_worker_registry()
        if stale_after_seconds < 0:
            raise ValueError("stale_after_seconds must be non-negative")
        if worker_id:
            record = registry.get(worker_id)
            records = [record] if record else []
        else:
            records = registry.list()
        reference = _coerce_datetime(now)
        return WorkerStatusResult(
            worker_id=worker_id,
            stale_after_seconds=stale_after_seconds,
            workers=[
                WorkerHeartbeatStatus.from_record(
                    record,
                    now=reference,
                    stale_after_seconds=stale_after_seconds,
                )
                for record in records
            ],
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

    def _record_worker_heartbeat(
        self,
        *,
        worker_id: str,
        queue_names: list[str],
        status: WorkerStatus | str,
        current_task_id: str | None = None,
        processed_increment: int = 0,
        failed_increment: int = 0,
        metadata: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> WorkerHeartbeat:
        registry = self.worker_registry
        if registry is None:
            return WorkerHeartbeat(
                worker_id=worker_id,
                queue_names=_unique_queue_names(queue_names),
                status=WorkerStatus(status),
                started_at=_coerce_datetime(now),
                last_heartbeat_at=_coerce_datetime(now),
                current_task_id=current_task_id,
            )
        reference = _coerce_datetime(now)
        existing = registry.get(worker_id)
        previous_metadata = existing.metadata if existing else {}
        worker = WorkerHeartbeat(
            worker_id=worker_id,
            queue_names=_unique_queue_names(queue_names or (existing.queue_names if existing else [])),
            status=WorkerStatus(status),
            started_at=existing.started_at if existing else reference,
            last_heartbeat_at=reference,
            current_task_id=current_task_id,
            processed_count=(existing.processed_count if existing else 0) + processed_increment,
            failed_count=(existing.failed_count if existing else 0) + failed_increment,
            metadata={**previous_metadata, **(metadata or {})},
        )
        registry.save(worker)
        return worker

    def _require_worker_registry(self) -> RedisWorkerRegistry:
        if self.worker_registry is None:
            raise RuntimeError("worker registry is not configured")
        return self.worker_registry


def _redis_client_from_url(redis_url: str | None):
    import redis

    url = redis_url or os.environ.get("NEWS_REDIS_URL", DEFAULT_REDIS_URL)
    return redis.from_url(url, decode_responses=True)


def _coerce_datetime(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _unique_queue_names(queue_names: list[str]) -> list[str]:
    return list(dict.fromkeys(str(queue_name) for queue_name in queue_names))


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
