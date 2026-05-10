from storage.memory import MemoryIngestionResult
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
    }


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
