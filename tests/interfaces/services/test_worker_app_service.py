from core.framework.workers import LeasedTask, Task, TaskResult, TaskStatus
from interfaces.services.worker_service import DEFAULT_DAILY_QUEUE, DEFAULT_MEMORY_QUEUE, WorkerApplicationService


def test_worker_service_enqueue_daily_uses_queue() -> None:
    queue = _FakeQueue()
    service = WorkerApplicationService(queue=queue, handlers={})

    result = service.enqueue_daily(
        profile="live-offline",
        topic="AI policy",
        source_limit=2,
        run_id="queued-run",
    )

    assert result.task.task_type == "daily_intelligence.run"
    assert result.task.queue_name == DEFAULT_DAILY_QUEUE
    assert result.task.payload == {
        "profile": "live-offline",
        "topic": "AI policy",
        "source_limit": 2,
        "run_id": "queued-run",
    }
    assert result.message_id == "1-0"
    assert queue.enqueued[0] is result.task


def test_worker_service_enqueue_memory_reindex_uses_memory_queue() -> None:
    queue = _FakeQueue()
    service = WorkerApplicationService(queue=queue, handlers={})

    result = service.enqueue_memory_reindex(run_id="run-1", topic="AI policy")

    assert result.task.task_type == "memory.reindex"
    assert result.task.queue_name == DEFAULT_MEMORY_QUEUE
    assert result.task.payload == {"run_id": "run-1", "topic": "AI policy"}
    assert result.message_id == "1-0"
    assert queue.enqueued[0] is result.task


def test_worker_service_run_once_acks_success() -> None:
    task = Task(task_type="daily_intelligence.run", payload={"topic": "AI"}, task_id="task-1")
    queue = _FakeQueue(leased=LeasedTask(DEFAULT_DAILY_QUEUE, "1-0", task))
    handler = _FakeHandler(success=True)
    service = WorkerApplicationService(queue=queue, handlers={handler.task_type: handler})

    result = service.run_once(worker_id="worker-1", block_ms=10)

    assert result.processed is True
    assert result.success is True
    assert result.workflow_run_id == "workflow-1"
    assert queue.acked == [(DEFAULT_DAILY_QUEUE, "1-0")]
    assert queue.dead_letters == []


def test_worker_service_run_once_requeues_failed_task_before_max_attempts() -> None:
    task = Task(
        task_type="daily_intelligence.run",
        payload={"topic": "AI"},
        task_id="task-1",
        attempts=1,
        max_attempts=3,
    )
    queue = _FakeQueue(leased=LeasedTask(DEFAULT_DAILY_QUEUE, "1-0", task))
    handler = _FakeHandler(success=False)
    service = WorkerApplicationService(queue=queue, handlers={handler.task_type: handler})

    result = service.run_once(worker_id="worker-1", block_ms=10)

    assert result.success is False
    assert queue.enqueued == [task]
    assert queue.dead_letters == []
    assert queue.acked == [(DEFAULT_DAILY_QUEUE, "1-0")]


def test_worker_service_run_once_dead_letters_exhausted_task() -> None:
    task = Task(
        task_type="daily_intelligence.run",
        payload={"topic": "AI"},
        task_id="task-1",
        attempts=3,
        max_attempts=3,
    )
    queue = _FakeQueue(leased=LeasedTask(DEFAULT_DAILY_QUEUE, "1-0", task))
    handler = _FakeHandler(success=False)
    service = WorkerApplicationService(queue=queue, handlers={handler.task_type: handler})

    result = service.run_once(worker_id="worker-1", block_ms=10)

    assert result.success is False
    assert queue.enqueued == []
    assert queue.dead_letters == [(task, "failed")]
    assert queue.acked == [(DEFAULT_DAILY_QUEUE, "1-0")]


class _FakeQueue:
    def __init__(self, leased=None) -> None:
        self.leased = leased
        self.enqueued = []
        self.acked = []
        self.dead_letters = []

    def enqueue(self, task):
        self.enqueued.append(task)
        return "1-0"

    def lease_one(self, worker_id, queue_names, *, block_ms):
        return self.leased

    def ack(self, queue_name, message_id):
        self.acked.append((queue_name, message_id))

    def move_to_dead_letter(self, task, reason):
        self.dead_letters.append((task, reason))


class _FakeHandler:
    task_type = "daily_intelligence.run"

    def __init__(self, *, success) -> None:
        self.success = success

    def handle(self, task):
        return TaskResult(
            task_id=task.task_id,
            success=self.success,
            status=TaskStatus.SUCCEEDED if self.success else TaskStatus.FAILED,
            workflow_run_id="workflow-1" if self.success else None,
            error_type=None if self.success else "FakeFailure",
            error_message=None if self.success else "failed",
        )
