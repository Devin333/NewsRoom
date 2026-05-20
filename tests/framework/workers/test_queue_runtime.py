from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from framework.workers import (
    InMemoryTaskQueue,
    Task,
    TaskHandlerRegistry,
    TaskResult,
    TaskStatus,
    WorkerLoop,
)
from framework.workers.queue.base import QueueStatus


@dataclass
class _Handler:
    task_type: str = "demo"

    def handle(self, task: Task) -> TaskResult:
        return TaskResult.success(task.task_id, {"seen": task.payload["value"]})


def test_in_memory_queue_supports_legacy_and_prd_lease_shapes() -> None:
    queue = InMemoryTaskQueue()
    first = Task(task_type="demo", payload={}, queue_name="q")
    second = Task(task_type="demo", payload={}, queue_name="q")
    queue.enqueue(first)
    queue.enqueue(second)

    legacy = queue.lease("worker-1", ["q"])
    assert isinstance(legacy, Task)
    assert legacy.status == TaskStatus.LEASED

    leased = queue.lease("q", "worker-2", 30, limit=1)
    assert len(leased) == 1
    assert leased[0].task.leased_by == "worker-2"


def test_worker_loop_accepts_handler_registry() -> None:
    queue = InMemoryTaskQueue()
    task = Task(task_type="demo", payload={"value": 3}, queue_name="q")
    queue.enqueue(task)
    registry = TaskHandlerRegistry()
    registry.register(_Handler())

    loop = WorkerLoop(
        worker_id="worker-1",
        queue=queue,
        handler_registry=registry,
        queue_name="q",
        idle_sleep_seconds=0,
    )

    result = loop.run_once()

    assert result is not None
    assert result.success
    assert queue.status("q").pending_count == 0


def test_worker_loop_accepts_task_queue_protocol() -> None:
    task = Task(task_type="demo", payload={"value": 7}, queue_name="q")
    queue = _FakeTaskQueue(task)

    loop = WorkerLoop(
        worker_id="worker-1",
        queue=queue,
        handlers={"demo": _Handler()},
        queue_name="q",
        idle_sleep_seconds=0,
    )

    result = loop.run_once()

    assert result is not None
    assert result.success
    assert queue.acked == [("task", "worker-1")]
    assert queue.failed == []


class _FakeTaskQueue:
    def __init__(self, task: Task) -> None:
        task.task_id = "task"
        self._task: Task | None = task
        self.acked: list[tuple[str, str | None]] = []
        self.failed: list[tuple[str, str, Any]] = []

    def enqueue(self, task: Task):
        self._task = task
        return None

    def lease(self, worker_id: str, queue_names: list[str]) -> Task | None:
        _ = worker_id, queue_names
        task = self._task
        self._task = None
        return task

    def ack(self, task_id: str, worker_id: str | None = None) -> None:
        self.acked.append((task_id, worker_id))

    def fail(self, task_id: str, worker_id: str, error: Any) -> None:
        self.failed.append((task_id, worker_id, error))

    def reclaim_stale(self, worker_id: str, queue_names: list[str]) -> Task | None:
        _ = worker_id, queue_names
        return None

    def status(self, queue: str | None = None) -> QueueStatus:
        return QueueStatus(queue_name=queue or "q")
