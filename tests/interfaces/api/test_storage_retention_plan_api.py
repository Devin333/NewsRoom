from datetime import UTC, datetime

from fastapi.testclient import TestClient

from interfaces.api import create_app
from interfaces.services.storage_service import StorageApplicationService
from infrastructure.storage.artifacts import ArtifactWriteRequest, FilesystemArtifactStore, LocalJsonArtifactIndexStore


def test_storage_retention_plan_api_maps_query_overrides() -> None:
    fake_service = _FakeStorageService()
    client = TestClient(create_app(storage_service_factory=lambda: fake_service))

    response = client.get(
        "/api/v1/storage/retention/plan"
        "?run_id=run-1"
        "&now=2026-05-11T00:00:00Z"
        "&raw_source_retention_days=7"
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["policy"]["raw_source_retention_days"] == 7
    assert fake_service.calls[0]["run_id"] == "run-1"
    assert fake_service.calls[0]["now"].isoformat().replace("+00:00", "Z") == "2026-05-11T00:00:00Z"


def test_storage_retention_plan_api_invalid_policy_uses_unified_error() -> None:
    client = TestClient(create_app(storage_service_factory=lambda: _FakeStorageService()))

    response = client.get("/api/v1/storage/retention/plan?raw_source_retention_days=-1")
    payload = response.json()

    assert response.status_code == 400
    assert payload["success"] is False
    assert payload["error"]["code"] == "invalid_storage_retention_request"


def test_storage_retention_plan_api_reads_real_artifact_index(tmp_path) -> None:
    artifact_store = FilesystemArtifactStore(tmp_path)
    artifact_index = LocalJsonArtifactIndexStore(tmp_path / "_records" / "artifact_index")
    ref = artifact_store.write(
        ArtifactWriteRequest(
            run_id="run-1",
            artifact_id="raw-old",
            artifact_type="source_item",
            content=b"raw",
            content_type="text/plain",
            created_at=datetime(2026, 4, 1, tzinfo=UTC),
        )
    )
    artifact_index.index_artifact(ref)
    client = TestClient(
        create_app(storage_service_factory=lambda: StorageApplicationService(tmp_path))
    )

    response = client.get("/api/v1/storage/retention/plan?now=2026-05-11T00:00:00Z")
    payload = response.json()

    assert response.status_code == 200
    assert payload["data"]["artifact_count"] == 1
    assert payload["data"]["delete_count"] == 1
    assert payload["data"]["plan"]["decisions"][0]["artifact_ref"]["artifact_id"] == "raw-old"


class _FakeStorageService:
    def __init__(self) -> None:
        self.calls = []

    def plan_retention(self, *, policy, run_id=None, now=None):
        self.calls.append({"policy": policy, "run_id": run_id, "now": now})
        return _Result(
            {
                "artifact_root": ".newsroom/runs",
                "run_id": run_id,
                "policy": policy.to_dict(),
                "artifact_count": 0,
                "delete_count": 0,
                "keep_count": 0,
                "plan": {
                    "generated_at": "2026-05-11T00:00:00Z",
                    "delete_count": 0,
                    "keep_count": 0,
                    "decisions": [],
                },
            }
        )


class _Result:
    def __init__(self, payload) -> None:
        self.payload = payload

    def to_dict(self):
        return self.payload
