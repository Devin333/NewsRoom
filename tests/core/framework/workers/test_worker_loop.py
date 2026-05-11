from core.framework.workers import (
    DailyIntelligenceTaskHandler,
    InMemoryTaskQueue,
    MemoryReindexTaskHandler,
    Task,
    WorkerLoop,
)
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
    assert queue.lease("worker-1", ["news:queue:daily"]) is None


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
    assert result.output["documents_indexed"] == 3


class _FakeRunService:
    def run_daily(self, *, profile, topic, source_limit, run_id):
        return _FakeRunResult(run_id=run_id)


class _FakeRunResult:
    def __init__(self, run_id):
        self.run_id = run_id
        self.status = TaskStatus.SUCCEEDED
        self.error = None

    def to_dict(self):
        return {"run_id": self.run_id, "status": "succeeded"}


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
