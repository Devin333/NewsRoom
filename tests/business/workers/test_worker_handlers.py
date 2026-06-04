from business.workers import (
    MemoryReindexTaskHandler,
    SourceHealthCheckTaskHandler,
)
from framework.workers import Task


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
