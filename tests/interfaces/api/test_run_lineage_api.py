from datetime import UTC, datetime

from fastapi.testclient import TestClient

from interfaces.api import create_app
from interfaces.services.storage_service import StorageApplicationService
from infrastructure.storage.lineage import LineageRef, LocalJsonLineageStore


def test_run_lineage_api_lists_lineage() -> None:
    fake_service = _FakeStorageService()
    client = TestClient(create_app(storage_service_factory=lambda: fake_service))

    response = client.get("/api/v2/graph-runs/run-1/lineage")
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["lineage_count"] == 1
    assert fake_service.calls == [("list", {"run_id": "run-1"})]


def test_run_lineage_api_queries_upstream_and_downstream() -> None:
    fake_service = _FakeStorageService()
    client = TestClient(create_app(storage_service_factory=lambda: fake_service))

    upstream_response = client.get(
        "/api/v2/graph-runs/run-1/lineage/upstream?target_type=evidence&target_id=ev-1"
    )
    downstream_response = client.get(
        "/api/v2/graph-runs/run-1/lineage/downstream?source_type=source_item&source_id=raw-1"
    )

    assert upstream_response.status_code == 200
    assert downstream_response.status_code == 200
    assert fake_service.calls == [
        (
            "upstream",
            {"run_id": "run-1", "target_type": "evidence", "target_id": "ev-1"},
        ),
        (
            "downstream",
            {"run_id": "run-1", "source_type": "source_item", "source_id": "raw-1"},
        ),
    ]


def test_run_lineage_api_invalid_request_uses_unified_error() -> None:
    client = TestClient(create_app(storage_service_factory=lambda: _InvalidStorageService()))

    response = client.get("/api/v2/graph-runs/bad/lineage")
    payload = response.json()

    assert response.status_code == 400
    assert payload["success"] is False
    assert payload["error"]["code"] == "invalid_lineage_request"


def test_run_lineage_api_reads_real_local_json_store(tmp_path) -> None:
    store = LocalJsonLineageStore(tmp_path / "_records" / "lineage")
    store.record(
        LineageRef(
            run_id="run-1",
            source_type="claim",
            source_id="claim-1",
            target_type="report",
            target_id="run-1:final",
            relation_type="claim_to_report",
            created_at=datetime(2026, 5, 11, tzinfo=UTC),
        )
    )
    client = TestClient(
        create_app(storage_service_factory=lambda: StorageApplicationService(tmp_path))
    )

    response = client.get(
        "/api/v2/graph-runs/run-1/lineage/upstream?target_type=report&target_id=run-1:final"
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["data"]["lineage_count"] == 1
    assert payload["data"]["lineage_refs"][0]["source_type"] == "claim"




class _FakeStorageService:
    def __init__(self) -> None:
        self.calls = []

    def list_lineage(self, run_id):
        self.calls.append(("list", {"run_id": run_id}))
        return _Result(_payload(run_id, "list"))

    def lineage_upstream(self, *, run_id, target_type, target_id):
        self.calls.append(
            (
                "upstream",
                {"run_id": run_id, "target_type": target_type, "target_id": target_id},
            )
        )
        return _Result(_payload(run_id, "upstream"))

    def lineage_downstream(self, *, run_id, source_type, source_id):
        self.calls.append(
            (
                "downstream",
                {"run_id": run_id, "source_type": source_type, "source_id": source_id},
            )
        )
        return _Result(_payload(run_id, "downstream"))


class _InvalidStorageService:
    def list_lineage(self, run_id):
        raise ValueError(f"invalid run id: {run_id}")


class _Result:
    def __init__(self, payload) -> None:
        self.payload = payload

    def to_dict(self):
        return self.payload


def _payload(run_id, query_type):
    return {
        "artifact_root": ".newsroom/runs",
        "run_id": run_id,
        "query_type": query_type,
        "lineage_count": 1,
        "lineage_refs": [
            {
                "lineage_id": "lin-1",
                "run_id": run_id,
                "source_type": "source_item",
                "source_id": "raw-1",
                "target_type": "evidence",
                "target_id": "ev-1",
                "relation_type": "source_to_evidence",
                "created_at": "2026-05-11T00:00:00Z",
                "metadata": {},
            }
        ],
    }
