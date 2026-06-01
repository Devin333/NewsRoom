from business.layers.signal.worker_handlers import SourceHealthCheckTaskHandler
from business.boards.paper_radar.worker_handlers import PaperIngestTaskHandler
from framework.workers import (
    LeasedTask,
    Task,
    TaskResult,
    TaskStatus,
    WorkerStatus,
)
from framework import WorkflowRunner
from framework.specs import StepSpec, WorkflowSpec, WorkflowStatus
from framework.workflow import FunctionStepRegistry, WorkflowRunInspector
from infrastructure.storage.workers import RedisQueueStatus
from interfaces.services.worker_service import (
    DEFAULT_DAILY_QUEUE,
    DEFAULT_DEAD_LETTER_QUEUE,
    DEFAULT_MEMORY_QUEUE,
    DEFAULT_PAPER_QUEUE,
    DEFAULT_SOURCE_QUEUE,
    WorkerApplicationService,
)


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
    assert result.task.dedup_key is None
    assert result.message_id == "1-0"
    assert queue.enqueued[0] is result.task


def test_worker_service_enqueue_daily_without_run_id_uses_stable_dedup_key() -> None:
    queue = _FakeQueue()
    service = WorkerApplicationService(queue=queue, handlers={})

    result = service.enqueue_daily(
        profile="live-offline",
        topic="AI policy",
        source_limit=2,
    )

    assert result.task.dedup_key == "news:queue:daily:daily:live-offline:ai policy"


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


def test_worker_service_enqueue_paper_ingest_uses_paper_queue() -> None:
    queue = _FakeQueue()
    service = WorkerApplicationService(queue=queue, handlers={})

    result = service.enqueue_paper_ingest(candidate_limit=100, min_github_stars=50)

    assert result.task.task_type == "papers.ingest_github_arxiv_daily"
    assert result.task.queue_name == DEFAULT_PAPER_QUEUE
    assert result.task.payload == {"candidate_limit": 100, "min_github_stars": 50}
    assert result.task.dedup_key == "news:queue:papers:daily:github-arxiv"
    assert result.message_id == "1-0"
    assert queue.enqueued[0] is result.task


def test_worker_service_enqueue_paper_visual_compile_backfill_uses_paper_queue() -> None:
    queue = _FakeQueue()
    service = WorkerApplicationService(queue=queue, handlers={})

    result = service.enqueue_paper_visual_compile_backfill(limit=25, force=False, run_id="reader-backfill")

    assert result.task.task_type == "papers.visual_compile_backfill"
    assert result.task.queue_name == DEFAULT_PAPER_QUEUE
    assert result.task.payload == {"force": False, "limit": 25, "run_id": "reader-backfill"}
    assert result.task.dedup_key is None
    assert result.to_dict()["limit"] == 25
    assert result.message_id == "1-0"
    assert queue.enqueued[0] is result.task


def test_worker_service_enqueue_paper_visual_compile_backfill_uses_stable_dedup_key_without_run_id() -> None:
    queue = _FakeQueue()
    service = WorkerApplicationService(queue=queue, handlers={})

    result = service.enqueue_paper_visual_compile_backfill()

    assert result.task.dedup_key == "news:queue:papers:paper-visual-compile-backfill:missing"


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


def test_worker_service_run_once_dead_letters_non_retryable_task() -> None:
    task = Task(
        task_type="daily_intelligence.run",
        payload={"topic": "AI"},
        task_id="task-1",
        attempts=1,
        max_attempts=3,
    )
    queue = _FakeQueue(leased=LeasedTask(DEFAULT_DAILY_QUEUE, "1-0", task))
    handler = _FakeHandler(success=False, retryable=False)
    service = WorkerApplicationService(queue=queue, handlers={handler.task_type: handler})

    result = service.run_once(worker_id="worker-1", block_ms=10)

    assert result.success is False
    assert result.retryable is False
    assert queue.enqueued == []
    assert queue.dead_letters == [(task, "failed")]
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


def test_worker_service_records_and_lists_worker_status() -> None:
    registry = _FakeWorkerRegistry()
    service = WorkerApplicationService(queue=_FakeQueue(), worker_registry=registry, handlers={})

    result = service.record_heartbeat(
        worker_id="worker-1",
        queue_names=[DEFAULT_DAILY_QUEUE],
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


def test_worker_service_run_once_updates_worker_heartbeat_counters() -> None:
    task = Task(task_type="daily_intelligence.run", payload={"topic": "AI"}, task_id="task-1")
    queue = _FakeQueue(leased=LeasedTask(DEFAULT_DAILY_QUEUE, "1-0", task))
    registry = _FakeWorkerRegistry()
    handler = _FakeHandler(success=True)
    service = WorkerApplicationService(
        queue=queue,
        worker_registry=registry,
        handlers={handler.task_type: handler},
    )

    result = service.run_once(worker_id="worker-1", block_ms=10)

    assert result.success is True
    assert [record.current_task_id for record in registry.saved] == [None, "task-1", None]
    assert registry.saved[-1].processed_count == 1
    assert registry.saved[-1].failed_count == 0


def test_worker_service_run_once_reclaims_stale_task_when_no_new_task() -> None:
    task = Task(task_type="daily_intelligence.run", payload={"topic": "AI"}, task_id="task-1")
    queue = _FakeQueue(reclaimed=LeasedTask(DEFAULT_DAILY_QUEUE, "1-0", task))
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
    assert queue.reclaim_calls == [("worker-1", [DEFAULT_DAILY_QUEUE], 60_000)]
    assert queue.acked == [(DEFAULT_DAILY_QUEUE, "1-0")]


def test_worker_service_reclaims_stale_workflow_task_and_persists_valid_run(tmp_path) -> None:
    task = Task(
        task_type="daily_intelligence.run",
        payload={"topic": "AI", "run_id": "worker-reclaimed-run"},
        task_id="task-reclaimed",
    )
    queue = _FakeQueue(reclaimed=LeasedTask(DEFAULT_DAILY_QUEUE, "9-0", task))
    handler = _WorkflowRunHandler(tmp_path)
    service = WorkerApplicationService(queue=queue, handlers={handler.task_type: handler})

    result = service.run_once(
        worker_id="worker-reclaimer",
        block_ms=10,
        reclaim_stale_ms=60_000,
    )

    inspection = WorkflowRunInspector(tmp_path).inspect_run("worker-reclaimed-run", strict=True)
    replay = WorkflowRunInspector(tmp_path).build_replay_bundle(
        "worker-reclaimed-run",
        strict=True,
    )
    assert result.processed is True
    assert result.reclaimed is True
    assert result.success is True
    assert result.workflow_run_id == "worker-reclaimed-run"
    assert handler.calls == [task.task_id]
    assert queue.reclaim_calls == [("worker-reclaimer", [DEFAULT_DAILY_QUEUE], 60_000)]
    assert queue.acked == [(DEFAULT_DAILY_QUEUE, "9-0")]
    assert inspection.status == "succeeded"
    assert inspection.integrity.valid is True
    assert replay.integrity["valid"] is True
    assert replay.output["report"] == "Reclaimed: AI"


def test_worker_service_queue_status_uses_default_queues() -> None:
    queue = _FakeQueue()
    service = WorkerApplicationService(queue=queue, handlers={})

    result = service.queue_status()

    payload = result.to_dict()
    assert queue.status_calls == [
        [DEFAULT_DAILY_QUEUE, DEFAULT_MEMORY_QUEUE, DEFAULT_PAPER_QUEUE, DEFAULT_SOURCE_QUEUE, DEFAULT_DEAD_LETTER_QUEUE]
    ]
    assert payload["queue_count"] == 5
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


def test_paper_ingest_task_handler_calls_ingest_service() -> None:
    handler = PaperIngestTaskHandler(_FakePaperIngestService())
    task = Task(
        task_type="papers.ingest_github_arxiv_daily",
        payload={"candidate_limit": 100, "min_github_stars": 50, "run_id": "paper-run-1"},
        task_id="task-paper",
    )

    result = handler.handle(task)

    assert result.success is True
    assert result.status == TaskStatus.SUCCEEDED
    assert result.workflow_run_id == "paper-run-1"
    assert result.output["publishedCount"] == 1


def test_worker_service_run_loop_stops_after_max_tasks() -> None:
    tasks = [
        LeasedTask(DEFAULT_DAILY_QUEUE, "1-0", Task(task_type="daily_intelligence.run", payload={})),
        LeasedTask(DEFAULT_DAILY_QUEUE, "2-0", Task(task_type="daily_intelligence.run", payload={})),
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
    task_type = "daily_intelligence.run"

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


class _WorkflowRunHandler:
    task_type = "daily_intelligence.run"

    def __init__(self, artifact_root) -> None:
        self.artifact_root = artifact_root
        self.calls = []

    def handle(self, task):
        self.calls.append(task.task_id)
        registry = FunctionStepRegistry()
        registry.register(
            "worker.write",
            lambda buffer: {"report": f"Reclaimed: {buffer.read('request')['topic']}"},
        )
        runner = WorkflowRunner(artifact_root=self.artifact_root, function_registry=registry)
        result = runner.run(
            WorkflowSpec(
                workflow_id="worker-reclaimed",
                name="Worker Reclaimed",
                version="1.0",
                start_step_id="write",
                steps=[
                    StepSpec(
                        step_id="write",
                        implementation="worker.write",
                        read_keys=["request"],
                        write_keys=["report"],
                        required_output_keys=["report"],
                    )
                ],
            ),
            {"topic": task.payload["topic"]},
            profile="test",
            run_id=task.payload["run_id"],
        )
        return TaskResult(
            task_id=task.task_id,
            success=result.status == WorkflowStatus.SUCCEEDED,
            status=(
                TaskStatus.SUCCEEDED
                if result.status == WorkflowStatus.SUCCEEDED
                else TaskStatus.FAILED
            ),
            workflow_run_id=result.run_id,
            output={"status": result.status.value},
            error_type=result.error["error_type"] if result.error else None,
            error_message=result.error["message"] if result.error else None,
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


class _FakePaperIngestService:
    def run_daily_ingest(self, *, candidate_limit=None, min_github_stars=None, run_id=None):
        assert candidate_limit == 100
        assert min_github_stars == 50
        assert run_id == "paper-run-1"

        class Result:
            def to_dict(self):
                return {
                    "runId": "paper-run-1",
                    "status": "succeeded",
                    "publishedCount": 1,
                }

        return Result()


def _dt(value: str):
    from datetime import UTC, datetime

    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
