from fastapi.testclient import TestClient

from interfaces.api import create_app


def test_worker_status_api_lists_workers() -> None:
    fake_service = _FakeWorkerService()
    client = TestClient(create_app(worker_service_factory=lambda: fake_service))

    response = client.get("/api/v1/workers?stale_after_seconds=30")
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["worker_count"] == 1
    assert payload["data"]["workers"][0]["worker_id"] == "worker-1"
    assert fake_service.calls == [{"worker_id": None, "stale_after_seconds": 30}]


def test_worker_status_api_gets_worker_by_id() -> None:
    fake_service = _FakeWorkerService()
    client = TestClient(create_app(worker_service_factory=lambda: fake_service))

    response = client.get("/api/v1/workers/worker-1?stale_after_seconds=45")
    payload = response.json()

    assert response.status_code == 200
    assert payload["data"]["worker_id"] == "worker-1"
    assert payload["data"]["workers"][0]["worker_id"] == "worker-1"
    assert fake_service.calls == [{"worker_id": "worker-1", "stale_after_seconds": 45}]


def test_worker_status_api_invalid_threshold_uses_unified_error() -> None:
    client = TestClient(create_app(worker_service_factory=lambda: _RejectingWorkerService()))

    response = client.get("/api/v1/workers?stale_after_seconds=-1")
    payload = response.json()

    assert response.status_code == 400
    assert payload["success"] is False
    assert payload["error"]["code"] == "invalid_worker_status_request"


class _FakeWorkerService:
    def __init__(self) -> None:
        self.calls = []

    def list_worker_status(self, *, worker_id=None, stale_after_seconds=60):
        self.calls.append(
            {
                "worker_id": worker_id,
                "stale_after_seconds": stale_after_seconds,
            }
        )
        return _Result(
            {
                "worker_id": worker_id,
                "worker_count": 1,
                "unhealthy_count": 0,
                "stale_after_seconds": stale_after_seconds,
                "workers": [
                    {
                        "worker_id": "worker-1",
                        "queue_names": ["news:queue:memory"],
                        "status": "running",
                        "stored_status": "running",
                        "stale": False,
                        "started_at": "2026-05-11T00:00:00Z",
                        "last_heartbeat_at": "2026-05-11T00:00:10Z",
                        "current_task_id": None,
                        "processed_count": 1,
                        "failed_count": 0,
                        "metadata": {},
                    }
                ],
            }
        )


class _RejectingWorkerService:
    def list_worker_status(self, *, worker_id=None, stale_after_seconds=60):
        raise ValueError("stale_after_seconds must be non-negative")


class _Result:
    def __init__(self, payload) -> None:
        self.payload = payload

    def to_dict(self):
        return dict(self.payload)
