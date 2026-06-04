from fastapi.testclient import TestClient

from framework.workers import ScheduleNotFoundError
from interfaces.api import create_app


def test_schedule_api_lists_schedules() -> None:
    fake_service = _FakeScheduleService()
    client = TestClient(create_app(schedule_service_factory=lambda: fake_service))

    response = client.get("/api/v1/schedules?include_disabled=true")
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["schedule_count"] == 1
    assert fake_service.list_calls == [{"enabled_only": False}]


def test_schedule_api_upserts_task_interval_schedule() -> None:
    fake_service = _FakeScheduleService()
    client = TestClient(create_app(schedule_service_factory=lambda: fake_service))

    response = client.post(
        "/api/v1/schedules",
        json={
            "schedule_id": "memory-reindex",
            "name": "Memory Reindex",
            "trigger_type": "interval",
            "interval_seconds": 3600,
            "run_at": "2026-05-11T00:00:00Z",
            "task_type": "memory.reindex",
            "payload_template": {"run_id": "run-1", "topic": "AI policy"},
            "queue_name": "news:queue:memory",
        },
    )
    payload = response.json()
    record = fake_service.upserted_record

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["schedule_id"] == "memory-reindex"
    assert record.spec.schedule_id == "memory-reindex"
    assert record.spec.interval_seconds == 3600
    assert record.spec.task_type == "memory.reindex"
    assert record.spec.queue_name == "news:queue:memory"
    assert record.spec.payload_template == {
        "run_id": "run-1",
        "topic": "AI policy",
    }


def test_schedule_api_ticks_schedules() -> None:
    fake_service = _FakeScheduleService()
    client = TestClient(create_app(schedule_service_factory=lambda: fake_service))

    response = client.post(
        "/api/v1/schedules/tick",
        json={"now": "2026-05-11T01:00:00Z", "include_disabled": True},
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["enqueued_count"] == 1
    assert fake_service.tick_calls[0]["enabled_only"] is False
    assert fake_service.tick_calls[0]["now"].isoformat().replace("+00:00", "Z") == "2026-05-11T01:00:00Z"


def test_schedule_api_trigger_missing_schedule_uses_unified_error() -> None:
    client = TestClient(create_app(schedule_service_factory=lambda: _MissingScheduleService()))

    response = client.post("/api/v1/schedules/missing/trigger", json={})
    payload = response.json()

    assert response.status_code == 404
    assert payload["success"] is False
    assert payload["error"]["code"] == "schedule_not_found"


class _FakeScheduleService:
    def __init__(self) -> None:
        self.list_calls = []
        self.tick_calls = []
        self.upserted_record = None

    def list_schedules(self, *, enabled_only=False):
        self.list_calls.append({"enabled_only": enabled_only})
        return _Result(
            {
                "schedule_count": 1,
                "schedules": [
                    {
                        "spec": {
                            "schedule_id": "daily",
                            "trigger_type": "interval",
                            "enabled": True,
                        }
                    }
                ],
            }
        )

    def upsert_schedule(self, record):
        self.upserted_record = record
        return _Result({"schedule_id": record.schedule_id, "schedule": record.to_dict()})

    def upsert_task_schedule(self, **kwargs):
        from framework.workers import ScheduleRecord, ScheduleSpec

        record = ScheduleRecord(
            spec=ScheduleSpec(
                schedule_id=kwargs["schedule_id"],
                name=kwargs["name"],
                trigger_type=kwargs["trigger_type"],
                task_type=kwargs["task_type"],
                payload_template=kwargs["payload_template"],
                queue_name=kwargs["queue_name"],
                interval_seconds=kwargs["interval_seconds"],
                run_at=kwargs["run_at"],
            )
        )
        self.upserted_record = record
        return _Result({"schedule_id": record.schedule_id, "schedule": record.to_dict()})

    def tick(self, *, now=None, enabled_only=True):
        self.tick_calls.append({"now": now, "enabled_only": enabled_only})
        return _Result(
            {
                "evaluated_count": 1,
                "enqueued_count": 1,
                "evaluations": [],
                "enqueued": [],
                "state_updates": {"daily": "2026-05-11T01:00:00Z"},
                "updated_schedules": [],
            }
        )

    def trigger_manual(self, schedule_id, *, now=None):
        return _Result({"schedule_id": schedule_id, "enqueued": {}, "updated_schedule": {}})


class _MissingScheduleService:
    def trigger_manual(self, schedule_id, *, now=None):
        raise ScheduleNotFoundError(schedule_id)


class _Result:
    def __init__(self, payload) -> None:
        self.payload = payload

    def to_dict(self):
        return self.payload
