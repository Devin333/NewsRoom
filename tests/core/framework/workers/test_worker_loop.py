from core.framework.workers import (
    InMemoryTaskQueue,
    Task,
    TaskRetryPolicy,
    WorkerLoop,
)
from core.framework.workers.models import TaskResult, TaskStatus


def test_worker_loop_runs_handler_once() -> None:
    queue = InMemoryTaskQueue()
    task = Task(
        task_type="sample.run",
        payload={"run_id": "worker-run"},
    )
    queue.enqueue(task)
    handler = _RunOnceHandler()
    worker = WorkerLoop(
        worker_id="worker-1",
        queue=queue,
        handlers={handler.task_type: handler},
        queue_names=[task.queue_name],
    )

    result = worker.run_once()

    assert result.success is True
    assert result.workflow_run_id == "worker-run"
    assert result.run_status == "succeeded"
    assert result.output["run_id"] == "worker-run"
    assert task.status == TaskStatus.SUCCEEDED
    assert [event.event_type for event in worker.events] == ["task_started", "task_succeeded"]
    assert queue.lease("worker-1", [task.queue_name]) is None


def test_worker_loop_retries_handler_infrastructure_failure_without_raising() -> None:
    queue = InMemoryTaskQueue(
        retry_policy=TaskRetryPolicy(retryable_error_types=["TimeoutError"], base_delay_seconds=5)
    )
    task = Task(
        task_type="unstable",
        payload={},
        task_id="task-1",
        max_attempts=2,
    )
    queue.enqueue(task)
    worker = WorkerLoop(
        worker_id="worker-1",
        queue=queue,
        handlers={"unstable": _FailingHandler()},
        queue_names=["news:queue:daily"],
    )

    result = worker.run_once()

    assert result.success is False
    assert result.error_type == "TimeoutError"
    assert task.status == TaskStatus.QUEUED
    assert task.metadata["last_error"]["error_type"] == "TimeoutError"
    assert task.scheduled_for is not None
    assert any(event.event_type == "task_retry_scheduled" for event in queue.events)


def test_worker_loop_pauses_approval_task_without_acknowledging() -> None:
    queue = InMemoryTaskQueue()
    task = Task(task_type="approval", payload={}, task_id="task-1")
    queue.enqueue(task)
    worker = WorkerLoop(
        worker_id="worker-1",
        queue=queue,
        handlers={"approval": _StaticHandler(TaskStatus.WAITING_FOR_APPROVAL)},
        queue_names=["news:queue:daily"],
    )

    result = worker.run_once()

    assert result.success is True
    assert result.status == TaskStatus.WAITING_FOR_APPROVAL
    assert task.status == TaskStatus.WAITING_FOR_APPROVAL
    assert task.metadata["lease_count"] == 1
    assert queue.queue_status("news:queue:daily").leased_count == 1
    assert worker.events[-1].event_type == "task_paused"


def test_worker_loop_does_not_retry_business_task_failure() -> None:
    queue = InMemoryTaskQueue()
    task = Task(task_type="business-failure", payload={}, task_id="task-1", max_attempts=2)
    queue.enqueue(task)
    worker = WorkerLoop(
        worker_id="worker-1",
        queue=queue,
        handlers={"business-failure": _BusinessFailureHandler()},
        queue_names=["news:queue:daily"],
    )

    result = worker.run_once()

    assert result.success is False
    assert result.error_type == "StepFailed"
    assert task.status == TaskStatus.DEAD_LETTER
    assert queue.list_dead_letters()[0].error.retryable is False


def test_worker_loop_run_stops_on_max_tasks() -> None:
    queue = InMemoryTaskQueue()
    queue.enqueue(Task(task_type="static", payload={}, task_id="task-1"))
    queue.enqueue(Task(task_type="static", payload={}, task_id="task-2"))
    worker = WorkerLoop(
        worker_id="worker-1",
        queue=queue,
        handlers={"static": _StaticHandler(TaskStatus.SUCCEEDED)},
        queue_names=["news:queue:daily"],
    )

    result = worker.run(max_tasks=2, idle_sleep_seconds=0)

    assert result.processed_count == 2
    assert result.succeeded_count == 2
    assert result.stop_reason == "max_tasks"


def test_worker_loop_run_stops_on_max_idle_polls() -> None:
    slept = []
    worker = WorkerLoop(
        worker_id="worker-1",
        queue=InMemoryTaskQueue(),
        handlers={},
        queue_names=["news:queue:daily"],
        sleep_fn=slept.append,
    )

    result = worker.run(max_idle_polls=2, idle_sleep_seconds=0)

    assert result.iterations == 2
    assert result.idle_count == 2
    assert result.stop_reason == "max_idle_polls"
    assert slept == []


class _FailingHandler:
    def handle(self, task):
        raise TimeoutError("temporary outage")


class _RunOnceHandler:
    task_type = "sample.run"

    def handle(self, task):
        return TaskResult(
            task_id=task.task_id,
            success=True,
            status=TaskStatus.SUCCEEDED,
            workflow_run_id=task.payload["run_id"],
            run_status="succeeded",
            output={"run_id": task.payload["run_id"]},
        )


class _StaticHandler:
    def __init__(self, status: TaskStatus) -> None:
        self.status = status

    def handle(self, task):
        return TaskResult(
            task_id=task.task_id,
            success=True,
            status=self.status,
            output={"run_id": task.payload.get("run_id")},
        )


class _BusinessFailureHandler:
    def handle(self, task):
        return TaskResult(
            task_id=task.task_id,
            success=False,
            status=TaskStatus.FAILED,
            error_type="StepFailed",
            error_message="quality workflow step failed",
        )
