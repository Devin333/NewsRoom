from __future__ import annotations

from dataclasses import dataclass

from framework.workers import (
    InMemoryTaskQueue,
    Task,
    TaskHandlerRegistry,
    TaskResult,
    TaskStatus,
    WorkerLoop,
)


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
