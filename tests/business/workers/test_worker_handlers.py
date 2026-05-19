from business.workers import (
    DailyIntelligenceTaskHandler,
    MemoryReindexTaskHandler,
    SourceHealthCheckTaskHandler,
)
from core.framework.specs import WorkflowStatus
from core.framework.workers import InMemoryTaskQueue, Task, WorkerLoop
from core.framework.workers.models import TaskStatus


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
    assert result.task_status == TaskStatus.SUCCEEDED
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
    assert result.task_status == TaskStatus.WAITING_FOR_APPROVAL
    assert result.run_status == "waiting_for_human"
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
