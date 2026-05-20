from business.layers.output.memory_ingestion import MemoryIngestionResult
from core.framework.run_result import RunResult
from core.framework.specs import WorkflowStatus
from interfaces.services.run_service import RunApplicationService


def test_run_service_does_not_index_memory_by_default(tmp_path, monkeypatch) -> None:
    import interfaces.services.run_service as run_service_module

    monkeypatch.delenv("NEWS_VECTOR_MEMORY_ENABLED", raising=False)
    monkeypatch.setattr(
        run_service_module,
        "repository_from_env",
        lambda artifact_root: _FakePersistenceRepository(),
    )

    result = RunApplicationService(artifact_root=tmp_path).run_daily(
        profile="live-offline",
        topic="AI policy",
        source_limit=1,
        run_id="no-memory-index",
    )

    assert "memory_ingestion_result" not in result.output


def test_run_service_indexes_memory_when_injected(tmp_path, monkeypatch) -> None:
    import interfaces.services.run_service as run_service_module

    fake_memory = _FakeMemoryIngestionService()
    monkeypatch.setattr(
        run_service_module,
        "repository_from_env",
        lambda artifact_root: _FakePersistenceRepository(),
    )

    result = RunApplicationService(
        artifact_root=tmp_path,
        memory_ingestion_service=fake_memory,
    ).run_daily(
        profile="live-offline",
        topic="AI policy",
        source_limit=1,
        run_id="memory-indexed",
    )

    assert fake_memory.calls[0]["run_id"] == "memory-indexed"
    assert fake_memory.calls[0]["topic"] == "AI policy"
    assert fake_memory.calls[0]["report_id"] == "memory-indexed:final"
    assert "final_report" in fake_memory.calls[0]["output"]
    assert "evidence_bundle" in fake_memory.calls[0]["output"]
    assert result.output["memory_ingestion_result"] == {
        "documents_indexed": 3,
        "collections": ["evidence_items", "report_sections"],
        "document_ids": ["doc-1", "doc-2", "doc-3"],
        "memories_written": 0,
        "memory_ids": [],
    }


def test_run_service_migrates_repository_before_daily_workflow(tmp_path, monkeypatch) -> None:
    import interfaces.services.run_service as run_service_module

    order = []
    fake_repository = _RecordingPersistenceRepository(order)
    monkeypatch.setattr(
        run_service_module,
        "repository_from_env",
        lambda artifact_root: fake_repository,
    )
    monkeypatch.setattr(
        run_service_module,
        "_daily_runner_cls",
        lambda profile: (lambda artifact_root: _RecordingDailyRunner(order)),
    )

    result = RunApplicationService(artifact_root=tmp_path).run_daily(
        profile="live-offline",
        topic="AI policy",
        source_limit=1,
        run_id="preflight-migrated",
    )

    assert result.run_id == "preflight-migrated"
    assert order == ["migrate", "run", "save_workflow_run"]


class _FakeMemoryIngestionService:
    def __init__(self) -> None:
        self.calls = []

    def ingest_run_output(self, output, *, run_id, report_id, topic):
        self.calls.append(
            {
                "output": output,
                "run_id": run_id,
                "report_id": report_id,
                "topic": topic,
            }
        )
        return MemoryIngestionResult(
            documents_indexed=3,
            collections=["evidence_items", "report_sections"],
            document_ids=["doc-1", "doc-2", "doc-3"],
        )


class _FakePersistenceRepository:
    def migrate(self) -> None:
        return None

    def save_workflow_run(self, record) -> None:
        return None

    def save_report(self, record) -> None:
        return None


class _RecordingPersistenceRepository:
    def __init__(self, order) -> None:
        self.order = order

    def migrate(self) -> None:
        self.order.append("migrate")

    def save_workflow_run(self, record) -> None:
        self.order.append("save_workflow_run")

    def save_report(self, record) -> None:
        self.order.append("save_report")


class _RecordingDailyRunner:
    def __init__(self, order) -> None:
        self.order = order

    def run(self, *, profile, topic, source_limit, run_id=None):
        self.order.append("run")
        return RunResult(
            run_id=run_id or "generated",
            workflow_id="daily_intelligence",
            workflow_version="1",
            status=WorkflowStatus.SUCCEEDED,
            output={},
        )
