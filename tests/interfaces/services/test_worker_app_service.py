from business.layers.signal.worker_handlers import SourceHealthCheckTaskHandler
from framework.shared.attempts import current_attempt_context
from framework.workers import LeasedTask, Task, TaskResult, TaskStatus, WorkerStatus
from infrastructure.storage.workers import RedisQueueStatus
from interfaces.services.worker_service import (
    DEFAULT_DEAD_LETTER_QUEUE,
    DEFAULT_MEMORY_QUEUE,
    DEFAULT_SOURCE_QUEUE,
    WorkerApplicationService,
)


def test_worker_service_status_does_not_build_default_task_handlers() -> None:
    class StatusOnlyService(WorkerApplicationService):
        def _build_default_handlers(self):
            raise AssertionError("queue and worker diagnostics must not build task handlers")

    registry = _FakeWorkerRegistry()
    service = StatusOnlyService(queue=_FakeQueue(), worker_registry=registry)
    service.record_heartbeat(worker_id="worker-1", queue_names=[DEFAULT_MEMORY_QUEUE])

    status = service.list_worker_status()
    queues = service.queue_status(queue_names=[DEFAULT_MEMORY_QUEUE])

    assert status.to_dict()["worker_count"] == 1
    assert queues.to_dict()["queue_count"] == 1


def test_worker_service_enqueue_memory_reindex_uses_memory_queue() -> None:
    queue = _FakeQueue()
    service = WorkerApplicationService(queue=queue, handlers={})

    result = service.enqueue_memory_reindex(run_id="run-1", topic="AI policy")

    assert result.task.task_type == "memory.reindex"
    assert result.task.queue_name == DEFAULT_MEMORY_QUEUE
    assert result.task.payload == {"run_id": "run-1", "topic": "AI policy"}
    assert result.message_id == "1-0"
    assert queue.enqueued[0] is result.task


def test_worker_service_enqueue_source_health_uses_source_queue() -> None:
    queue = _FakeQueue()
    service = WorkerApplicationService(queue=queue, handlers={})

    result = service.enqueue_source_health_check(
        source_id="source-1",
        limit=1,
        force=True,
    )

    assert result.task.task_type == "source_health_check"
    assert result.task.queue_name == DEFAULT_SOURCE_QUEUE
    assert result.task.payload == {
        "include_disabled": False,
        "force": True,
        "source_id": "source-1",
        "limit": 1,
    }
    assert result.message_id == "1-0"
    assert queue.enqueued[0] is result.task


def test_worker_service_default_redis_queue_uses_news_dead_letter_queue() -> None:
    service = WorkerApplicationService(redis_url="redis://127.0.0.1:6379/15", handlers={})

    assert service.queue.dead_letter_queue_name == DEFAULT_DEAD_LETTER_QUEUE


def test_worker_service_run_once_acks_success() -> None:
    task = Task(task_type="memory.reindex", payload={"run_id": "run-1"}, task_id="task-1")
    queue = _FakeQueue(leased=LeasedTask(DEFAULT_MEMORY_QUEUE, "1-0", task))
    handler = _FakeHandler(success=True)
    service = WorkerApplicationService(queue=queue, handlers={handler.task_type: handler})

    result = service.run_once(worker_id="worker-1", block_ms=10)

    assert result.processed is True
    assert result.success is True
    assert result.workflow_run_id == "workflow-1"
    assert queue.acked == [(DEFAULT_MEMORY_QUEUE, "1-0")]
    assert queue.dead_letters == []


def test_worker_service_run_once_requeues_failed_task_before_max_attempts() -> None:
    task = Task(
        task_type="memory.reindex",
        payload={"run_id": "run-1"},
        task_id="task-1",
        attempts=1,
        max_attempts=3,
    )
    queue = _FakeQueue(leased=LeasedTask(DEFAULT_MEMORY_QUEUE, "1-0", task))
    handler = _FakeHandler(success=False)
    service = WorkerApplicationService(queue=queue, handlers={handler.task_type: handler})

    result = service.run_once(worker_id="worker-1", block_ms=10)

    assert result.success is False
    assert queue.enqueued == [task]
    assert queue.dead_letters == []
    assert queue.acked == [(DEFAULT_MEMORY_QUEUE, "1-0")]


def test_worker_service_run_once_dead_letters_non_retryable_task() -> None:
    task = Task(
        task_type="memory.reindex",
        payload={"run_id": "run-1"},
        task_id="task-1",
        attempts=1,
        max_attempts=3,
    )
    queue = _FakeQueue(leased=LeasedTask(DEFAULT_MEMORY_QUEUE, "1-0", task))
    handler = _FakeHandler(success=False, retryable=False)
    service = WorkerApplicationService(queue=queue, handlers={handler.task_type: handler})

    result = service.run_once(worker_id="worker-1", block_ms=10)

    assert result.success is False
    assert result.retryable is False
    assert queue.enqueued == []
    assert queue.dead_letters == [(task, "task execution failed")]
    assert result.error_type == "WorkerInternalError"
    assert result.error_message == "task execution failed"
    assert result.error_id is not None
    assert queue.acked == [(DEFAULT_MEMORY_QUEUE, "1-0")]


def test_worker_service_records_and_lists_worker_status() -> None:
    registry = _FakeWorkerRegistry()
    service = WorkerApplicationService(queue=_FakeQueue(), worker_registry=registry, handlers={})

    result = service.record_heartbeat(
        worker_id="worker-1",
        queue_names=[DEFAULT_MEMORY_QUEUE],
        status=WorkerStatus.RUNNING,
        current_task_id="task-1",
        now=_dt("2026-05-11T00:00:00Z"),
    )

    payload = result.to_dict()["worker"]
    assert payload["worker_id"] == "worker-1"
    assert payload["status"] == "running"
    assert payload["current_task_id"] == "task-1"

    status = service.list_worker_status(
        stale_after_seconds=60,
        now=_dt("2026-05-11T00:02:00Z"),
    )

    status_payload = status.to_dict()
    assert status_payload["worker_count"] == 1
    assert status_payload["unhealthy_count"] == 1
    assert status_payload["workers"][0]["status"] == "unhealthy"
    assert status_payload["workers"][0]["stored_status"] == "running"


def test_worker_service_run_once_reclaims_stale_task_when_no_new_task() -> None:
    task = Task(task_type="memory.reindex", payload={"run_id": "run-1"}, task_id="task-1")
    queue = _FakeQueue(reclaimed=LeasedTask(DEFAULT_MEMORY_QUEUE, "1-0", task))
    handler = _FakeHandler(success=True)
    service = WorkerApplicationService(queue=queue, handlers={handler.task_type: handler})

    result = service.run_once(
        worker_id="worker-1",
        block_ms=10,
        reclaim_stale_ms=60_000,
    )

    assert result.processed is True
    assert result.reclaimed is True
    assert result.success is True
    assert task.attempts == 1
    assert task.metadata["lease_count"] == 1
    assert task.metadata["reclaimed"] is True
    assert queue.reclaim_calls == [("worker-1", [DEFAULT_MEMORY_QUEUE], 60_000)]
    assert queue.acked == [(DEFAULT_MEMORY_QUEUE, "1-0")]


def test_worker_service_binds_fenced_attempt_context_and_uses_guarded_ack() -> None:
    task = Task(task_type="memory.reindex", payload={}, task_id="task-1", attempts=2)
    leased = LeasedTask(
        DEFAULT_MEMORY_QUEUE,
        "1-0",
        task,
        owner_id="worker-1",
        lease_id="lease-2",
        fencing_token=2,
        attempt=2,
        effect_key="task:task-1",
    )
    queue = _FencedQueue(leased=leased)
    handler = _ContextCapturingHandler()
    service = WorkerApplicationService(queue=queue, handlers={handler.task_type: handler})

    result = service.run_once(worker_id="worker-1", block_ms=10)

    assert result.success is True
    assert handler.context is not None
    assert handler.context.attempt_id == "lease-2"
    assert handler.context.idempotency_key == "task:task-1"
    assert handler.context.fencing_token == 2
    assert queue.guarded_acks == [leased]
    assert queue.acked == []


def test_worker_service_lease_renewal_loss_cancels_context_and_rejects_terminal_write() -> None:
    task = Task(task_type="memory.reindex", payload={}, task_id="task-1", attempts=1)
    leased = LeasedTask(
        DEFAULT_MEMORY_QUEUE,
        "1-0",
        task,
        owner_id="worker-1",
        lease_id="lease-1",
        fencing_token=1,
        attempt=1,
        effect_key="task:task-1",
    )
    queue = _FencedQueue(leased=leased, lose_renewal=True)
    handler = _CooperativeLongHandler()
    service = WorkerApplicationService(queue=queue, handlers={handler.task_type: handler})

    result = service.run_once(worker_id="worker-1", block_ms=10)

    assert result.success is False
    assert result.retryable is False
    assert result.error_type == "StaleTaskLeaseError"
    assert result.error_message == "task lease is stale"
    assert result.error_id is not None
    assert handler.cancelled is True
    assert queue.guarded_acks == []
    assert queue.guarded_failures == []


def test_worker_service_raw_handler_exception_is_safe_and_keeps_correlation_id() -> None:
    secret = "postgresql://alice:hunter2@database.internal/news"
    task = Task(task_type="memory.reindex", payload={}, task_id="task-1", attempts=1)
    leased = LeasedTask(
        DEFAULT_MEMORY_QUEUE,
        "1-0",
        task,
        owner_id="worker-1",
        lease_id="lease-1",
        fencing_token=1,
        attempt=1,
        effect_key="task:task-1",
    )
    queue = _FencedQueue(leased=leased)
    handler = _ExplodingHandler(secret)
    service = WorkerApplicationService(queue=queue, handlers={handler.task_type: handler})

    result = service.run_once(worker_id="worker-1", block_ms=10)

    assert result.success is False
    assert result.error_type == "WorkerInternalError"
    assert result.error_message == "task execution failed"
    assert result.error_id is not None
    assert secret not in str(result.to_dict())
    assert len(queue.guarded_failures) == 1
    persisted_error = queue.guarded_failures[0][1]
    assert persisted_error.error_type == "WorkerInternalError"
    assert persisted_error.error_message == "task execution failed"
    assert persisted_error.error_id == result.error_id


def test_worker_service_queue_status_uses_default_queues() -> None:
    queue = _FakeQueue()
    service = WorkerApplicationService(queue=queue, handlers={})

    result = service.queue_status()

    payload = result.to_dict()
    assert queue.status_calls == [[DEFAULT_MEMORY_QUEUE, DEFAULT_SOURCE_QUEUE, DEFAULT_DEAD_LETTER_QUEUE]]
    assert payload["queue_count"] == 3
    assert payload["total_stream_length"] == 0


def test_source_health_check_task_handler_calls_source_service() -> None:
    handler = SourceHealthCheckTaskHandler(_FakeSourceService())
    task = Task(
        task_type="source_health_check",
        payload={"source_id": "source-1", "limit": 1, "force": True},
        task_id="task-1",
    )

    result = handler.handle(task)

    assert result.success is True
    assert result.status == TaskStatus.SUCCEEDED
    assert result.output["checked_count"] == 1
    assert result.output["entries"][0]["source_id"] == "source-1"


def test_worker_service_run_loop_stops_after_max_tasks() -> None:
    tasks = [
        LeasedTask(DEFAULT_MEMORY_QUEUE, "1-0", Task(task_type="memory.reindex", payload={})),
        LeasedTask(DEFAULT_MEMORY_QUEUE, "2-0", Task(task_type="memory.reindex", payload={})),
    ]
    queue = _FakeQueue(leased=tasks)
    handler = _FakeHandler(success=True)
    service = WorkerApplicationService(queue=queue, handlers={handler.task_type: handler})

    result = service.run_loop(
        worker_id="worker-1",
        max_tasks=2,
        idle_sleep_seconds=0,
    )

    payload = result.to_dict()
    assert payload["stop_reason"] == "max_tasks"
    assert payload["processed_count"] == 2
    assert payload["succeeded_count"] == 2
    assert payload["idle_count"] == 0


def test_worker_service_run_loop_stops_after_idle_polls() -> None:
    service = WorkerApplicationService(queue=_FakeQueue(), handlers={})

    result = service.run_loop(
        worker_id="worker-1",
        max_idle_polls=2,
        idle_sleep_seconds=0,
    )

    payload = result.to_dict()
    assert payload["stop_reason"] == "max_idle_polls"
    assert payload["processed_count"] == 0
    assert payload["idle_count"] == 2


class _FakeQueue:
    def __init__(self, leased=None, reclaimed=None) -> None:
        self.leased = leased
        self.reclaimed = reclaimed
        self.enqueued = []
        self.acked = []
        self.dead_letters = []
        self.reclaim_calls = []
        self.status_calls = []

    def enqueue(self, task):
        self.enqueued.append(task)
        return "1-0"

    def lease_one(self, worker_id, queue_names, *, block_ms):
        if isinstance(self.leased, list):
            if not self.leased:
                return None
            return self.leased.pop(0)
        return self.leased

    def reclaim_stale_one(self, worker_id, queue_names, *, min_idle_ms):
        self.reclaim_calls.append((worker_id, queue_names, min_idle_ms))
        if self.reclaimed is not None:
            task = self.reclaimed.task
            previous_worker = task.leased_by
            task.leased_by = worker_id
            task.attempts += 1
            task.metadata["lease_count"] = task.attempts
            task.metadata["reclaimed"] = True
            if previous_worker is not None and previous_worker != worker_id:
                task.metadata["reclaimed_from_worker"] = previous_worker
        return self.reclaimed

    def ack(self, queue_name, message_id):
        self.acked.append((queue_name, message_id))

    def move_to_dead_letter(self, task, reason):
        self.dead_letters.append((task, reason))

    def status(self, queue_names):
        self.status_calls.append(list(queue_names))
        return [
            RedisQueueStatus(
                queue_name=queue_name,
                stream_length=0,
                group_name="news-workers",
                group_exists=False,
            )
            for queue_name in queue_names
        ]


class _FencedQueue(_FakeQueue):
    def __init__(self, *, leased, lose_renewal=False) -> None:
        super().__init__(leased=leased)
        self.lose_renewal = lose_renewal
        self.guarded_acks = []
        self.guarded_failures = []

    def renewal_interval_seconds(self, leased):
        return 0.01

    def renew(self, leased):
        if self.lose_renewal:
            from framework.workers import StaleTaskLeaseError

            raise StaleTaskLeaseError(leased, operation="renew")
        return leased.lease_expires_at

    def ack(self, leased, message_id=None):
        if isinstance(leased, LeasedTask):
            self.guarded_acks.append(leased)
            return 1
        return super().ack(leased, message_id)

    def fail(self, leased, error):
        self.guarded_failures.append((leased, error))


class _ContextCapturingHandler:
    task_type = "memory.reindex"

    def __init__(self) -> None:
        self.context = None

    def handle(self, task):
        self.context = current_attempt_context()
        return TaskResult.success(task.task_id)


class _CooperativeLongHandler:
    task_type = "memory.reindex"

    def __init__(self) -> None:
        self.cancelled = False

    def handle(self, task):
        import time

        context = current_attempt_context()
        assert context is not None
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if context.cancelled:
                self.cancelled = True
                context.raise_if_cancelled()
            time.sleep(0.001)
        raise AssertionError("lease cancellation was not delivered")


class _ExplodingHandler:
    task_type = "memory.reindex"

    def __init__(self, secret) -> None:
        self.secret = secret

    def handle(self, task):
        raise RuntimeError(f"database rejected {self.secret}")


class _FakeWorkerRegistry:
    def __init__(self) -> None:
        self.records = {}
        self.saved = []

    def save(self, worker):
        self.records[worker.worker_id] = worker
        self.saved.append(worker)
        return worker

    def get(self, worker_id):
        return self.records.get(worker_id)

    def list(self):
        return list(self.records.values())


class _FakeHandler:
    task_type = "memory.reindex"

    def __init__(self, *, success, retryable=True) -> None:
        self.success = success
        self.retryable = retryable

    def handle(self, task):
        return TaskResult(
            task_id=task.task_id,
            success=self.success,
            retryable=self.retryable,
            status=TaskStatus.SUCCEEDED if self.success else TaskStatus.FAILED,
            workflow_run_id="workflow-1" if self.success else None,
            error_type=None if self.success else "FakeFailure",
            error_message=None if self.success else "failed",
        )


class _FakeSourceService:
    def check_source_health(self, **kwargs):
        assert kwargs == {
            "source_id": "source-1",
            "enabled_only": True,
            "limit": 1,
            "force": True,
        }
        return _FakeSourceHealthResult()


class _FakeSourceHealthResult:
    def to_dict(self):
        return {
            "checked_count": 1,
            "succeeded_count": 1,
            "failed_count": 0,
            "skipped_count": 0,
            "entries": [{"source_id": "source-1", "ok": True, "status": "healthy"}],
            "events": [],
        }


def _dt(value: str):
    from datetime import UTC, datetime

    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
