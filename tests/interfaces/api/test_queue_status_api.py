from fastapi.testclient import TestClient

from interfaces.api import create_app


def test_queue_status_api_reads_default_queues() -> None:
    fake_service = _FakeWorkerService()
    client = TestClient(create_app(worker_service_factory=lambda: fake_service))

    response = client.get("/api/v1/queues")
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["queue_count"] == 1
    assert fake_service.queue_status_calls == [None]


def test_queue_status_api_maps_repeated_queue_names() -> None:
    fake_service = _FakeWorkerService()
    client = TestClient(create_app(worker_service_factory=lambda: fake_service))

    response = client.get("/api/v1/queues?queue_name=news:queue:daily&queue_name=news:queue:memory")
    payload = response.json()

    assert response.status_code == 200
    assert payload["data"]["queues"][0]["queue_name"] == "news:queue:daily"
    assert payload["data"]["queues"][1]["queue_name"] == "news:queue:memory"
    assert fake_service.queue_status_calls == [["news:queue:daily", "news:queue:memory"]]


def test_queue_status_api_invalid_queue_request_uses_unified_error() -> None:
    client = TestClient(create_app(worker_service_factory=lambda: _RejectingWorkerService()))

    response = client.get("/api/v1/queues?queue_name=")
    payload = response.json()

    assert response.status_code == 400
    assert payload["success"] is False
    assert payload["error"]["code"] == "invalid_queue_status_request"


class _RejectingWorkerService:
    def queue_status(self, *, queue_names=None):
        raise ValueError("queue_names must not contain empty values")


class _FakeWorkerService:
    def __init__(self) -> None:
        self.queue_status_calls = []

    def queue_status(self, *, queue_names=None):
        self.queue_status_calls.append(queue_names)
        actual_queue_names = queue_names or ["news:queue:daily"]
        return _Result(
            {
                "queue_count": len(actual_queue_names),
                "total_stream_length": len(actual_queue_names),
                "total_pending_count": 0,
                "queues": [
                    {
                        "queue_name": queue_name,
                        "stream_length": 1,
                        "group_name": "news-workers",
                        "group_exists": True,
                        "pending_count": 0,
                        "consumer_count": 0,
                        "consumers": [],
                    }
                    for queue_name in actual_queue_names
                ],
            }
        )


class _Result:
    def __init__(self, payload) -> None:
        self.payload = payload

    def to_dict(self):
        return dict(self.payload)
