from core.framework.workers import DailyIntelligenceTaskHandler, InMemoryTaskQueue, Task, WorkerLoop
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
