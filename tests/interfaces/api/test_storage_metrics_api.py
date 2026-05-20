import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from interfaces.api import create_app
from interfaces.services.storage_service import StorageApplicationService
from infrastructure.storage.artifacts import ArtifactWriteRequest, FilesystemArtifactStore, LocalJsonArtifactIndexStore
from infrastructure.storage.metrics import StorageMetrics


def test_storage_metrics_api_returns_metrics() -> None:
    client = TestClient(create_app(storage_service_factory=lambda: _FakeStorageService()))

    response = client.get("/api/v1/storage/metrics")
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["runs_count"] == 1
    assert payload["data"]["metadata"]["source"] == "test"


def test_storage_metrics_api_reads_real_local_storage(tmp_path) -> None:
    artifact_store = FilesystemArtifactStore(tmp_path)
    artifact_index = LocalJsonArtifactIndexStore(tmp_path / "_records" / "artifact_index")
    ref = artifact_store.write(
        ArtifactWriteRequest(
            run_id="run-1",
            artifact_id="report-1",
            artifact_type="report_json",
            content=b'{"title":"Report"}',
            content_type="application/json",
            created_at=datetime(2026, 5, 11, tzinfo=UTC),
        )
    )
    artifact_index.index_artifact(ref)
    (tmp_path / "run-1" / "manifest.json").write_text(
        json.dumps({"run_id": "run-1", "artifacts": {"report_json": ref.path}}),
        encoding="utf-8",
    )
    events_dir = tmp_path / "_records" / "events"
    events_dir.mkdir(parents=True)
    (events_dir / "run-1.jsonl").write_text('{"event_type":"ok"}\n', encoding="utf-8")
    client = TestClient(
        create_app(storage_service_factory=lambda: StorageApplicationService(tmp_path))
    )

    response = client.get("/api/v1/storage/metrics")
    payload = response.json()

    assert response.status_code == 200
    assert payload["data"]["runs_count"] == 1
    assert payload["data"]["reports_count"] == 1
    assert payload["data"]["artifacts_count"] == 1
    assert payload["data"]["artifact_bytes_total"] == len(b'{"title":"Report"}')
    assert payload["data"]["events_count"] == 1


class _FakeStorageService:
    def metrics(self):
        return StorageMetrics(
            runs_count=1,
            reports_count=1,
            artifacts_count=2,
            artifact_bytes_total=42,
            events_count=3,
            lineage_refs_count=4,
            generated_at=datetime(2026, 5, 11, tzinfo=UTC),
            metadata={"source": "test"},
        )
