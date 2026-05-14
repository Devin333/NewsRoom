from core.framework.workers import (
    DailyIntelligenceTaskHandler,
    InMemoryTaskQueue,
    MemoryReindexTaskHandler,
    SourceHealthCheckTaskHandler,
    Task,
    TaskRetryPolicy,
    WorkerLoop,
)
from core.framework.specs import WorkflowStatus
from core.framework.workers.models import TaskResult, TaskStatus


def test_worker_loop_runs_daily_handler_once() -> None:
    queue = InMemoryTaskQueue()
    task = Task(
        task_type="daily_intelligence.run",
        payload={"profile": "live-offline", "topic": "AI", "source_limit": 1, "run_id": "worker-run"},
    )
    queue.enqueue(task)
    handler = DailyIntelligenceTaskHandler(run_service=_FakeRunService())
    worker = WorkerLoop(
        worker_id="worker-1",
        queue=queue,
        handlers={handler.task_type: handler},
        queue_names=["news:queue:daily"],
    )

    result = worker.run_once()

    assert result.success is True
    assert result.workflow_run_id == "worker-run"
    assert result.run_status == "succeeded"
    assert result.output["run_id"] == "worker-run"
    assert result.output["artifact_dir"] == "artifacts/worker-run"
    assert result.output["summary"] == {"title": "Daily summary"}
    assert task.status == TaskStatus.SUCCEEDED
    assert [event.event_type for event in worker.events] == ["task_started", "task_succeeded"]
    assert queue.lease("worker-1", ["news:queue:daily"]) is None


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


def test_daily_handler_maps_blocked_workflow_to_completed_task() -> None:
    task = Task(
        task_type="daily_intelligence.run",
        payload={"profile": "live-offline", "topic": "AI", "source_limit": 1, "run_id": "blocked-run"},
    )
    handler = DailyIntelligenceTaskHandler(
        run_service=_FakeRunService(
            status=WorkflowStatus.BLOCKED,
            error={"error_type": "QualityGateBlocked", "message": "quality gate blocked"},
            output={"blocked_report": {"title": "Blocked", "reasons": ["quality"]}},
        )
    )

    result = handler.handle(task)

    assert result.success is True
    assert result.status == TaskStatus.SUCCEEDED
    assert result.run_status == "blocked"
    assert result.report_status == "blocked"
    assert result.error_type is None
    assert result.output["status"] == "blocked"
    assert result.output["error"]["error_type"] == "QualityGateBlocked"
    assert result.output["output"]["blocked_report"]["title"] == "Blocked"


def test_daily_handler_maps_human_review_workflow_to_waiting_task() -> None:
    task = Task(
        task_type="daily_intelligence.run",
        payload={"profile": "live-offline", "topic": "AI", "source_limit": 1, "run_id": "human-run"},
    )
    handler = DailyIntelligenceTaskHandler(
        run_service=_FakeRunService(status=WorkflowStatus.WAITING_FOR_HUMAN)
    )

    result = handler.handle(task)

    assert result.success is True
    assert result.status == TaskStatus.WAITING_FOR_APPROVAL
    assert result.output["status"] == "waiting_for_human"


def test_daily_handler_maps_failed_workflow_to_failed_task() -> None:
    task = Task(
        task_type="daily_intelligence.run",
        payload={"profile": "live-offline", "topic": "AI", "source_limit": 1, "run_id": "failed-run"},
    )
    handler = DailyIntelligenceTaskHandler(
        run_service=_FakeRunService(
            status=WorkflowStatus.FAILED,
            error={"error_type": "StepFailed", "message": "step failed"},
        )
    )

    result = handler.handle(task)

    assert result.success is False
    assert result.status == TaskStatus.FAILED
    assert result.error_type == "StepFailed"
    assert result.error_message == "step failed"


def test_memory_reindex_handler_reindexes_run() -> None:
    task = Task(
        task_type="memory.reindex",
        payload={"run_id": "run-1", "topic": "AI policy"},
        task_id="task-1",
    )
    memory_service = _FakeMemoryService()
    handler = MemoryReindexTaskHandler(memory_service=memory_service)

    result = handler.handle(task)

    assert memory_service.calls == [{"run_id": "run-1", "topic": "AI policy"}]
    assert result.success is True
    assert result.workflow_run_id == "run-1"
    assert result.run_status == "succeeded"
    assert result.output["run_id"] == "run-1"
    assert result.output["artifact_dir"] is None
    assert result.output["summary"] == {}
    assert result.output["documents_indexed"] == 3


def test_memory_reindex_handler_allows_same_run_id_replay_with_stable_output() -> None:
    task = Task(
        task_type="memory.reindex",
        payload={"run_id": "run-1", "topic": "AI policy"},
        task_id="task-1",
    )
    memory_service = _FakeMemoryService()
    handler = MemoryReindexTaskHandler(memory_service=memory_service)

    first = handler.handle(task)
    second = handler.handle(task)

    assert len(memory_service.calls) == 2
    assert first.output == second.output


def test_source_health_handler_checks_sources_without_daily_workflow() -> None:
    task = Task(
        task_type="source_health_check",
        payload={"source_id": "source-1", "limit": 5, "run_id": "health-run"},
        task_id="task-1",
    )
    source_service = _FakeSourceService()
    handler = SourceHealthCheckTaskHandler(source_service=source_service)

    result = handler.handle(task)

    assert source_service.calls == [
        {
            "source_id": "source-1",
            "enabled_only": True,
            "limit": 5,
            "force": False,
        }
    ]
    assert result.success is True
    assert result.run_status == "succeeded"
    assert result.output["run_id"] == "health-run"
    assert result.output["artifact_dir"] is None
    assert result.output["summary"] == {"healthy": 1, "unhealthy": 0}


class _FakeRunService:
    def __init__(self, *, status=WorkflowStatus.SUCCEEDED, error=None, output=None) -> None:
        self.status = status
        self.error = error
        self.output = output or {"summary": {"title": "Daily summary"}}

    def run_daily(self, *, profile, topic, source_limit, run_id):
        return _FakeRunResult(
            run_id=run_id,
            status=self.status,
            error=self.error,
            output=self.output,
        )


class _FakeRunResult:
    def __init__(self, run_id, *, status, error, output):
        self.run_id = run_id
        self.status = status
        self.error = error
        self.output = output

    def to_dict(self):
        return {
            "run_id": self.run_id,
            "status": self.status.value,
            "artifact_dir": f"artifacts/{self.run_id}",
            "output": dict(self.output),
            "error": dict(self.error) if self.error else None,
        }


class _FakeMemoryService:
    def __init__(self) -> None:
        self.calls = []

    def reindex_run(self, run_id, *, topic=None):
        self.calls.append({"run_id": run_id, "topic": topic})
        return _FakeMemoryReindexResult(run_id, topic)


class _FakeMemoryReindexResult:
    def __init__(self, run_id, topic):
        self.run_id = run_id
        self.topic = topic

    def to_dict(self):
        return {
            "run_id": self.run_id,
            "topic": self.topic,
            "documents_indexed": 3,
            "collections": ["evidence_items", "report_sections"],
            "document_ids": ["doc-1", "doc-2", "doc-3"],
        }


class _FakeSourceService:
    def __init__(self) -> None:
        self.calls = []

    def check_source_health(self, *, source_id=None, enabled_only=True, limit=None, force=False):
        self.calls.append(
            {
                "source_id": source_id,
                "enabled_only": enabled_only,
                "limit": limit,
                "force": force,
            }
        )
        return _FakeSourceHealthResult()


class _FakeSourceHealthResult:
    def to_dict(self):
        return {
            "sources_checked": 1,
            "output": {"summary": {"healthy": 1, "unhealthy": 0}},
        }


class _FailingHandler:
    def handle(self, task):
        raise TimeoutError("temporary outage")


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
