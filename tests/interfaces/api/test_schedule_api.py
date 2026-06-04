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


def test_schedule_api_upserts_daily_interval_schedule() -> None:
    fake_service = _FakeScheduleService()
    client = TestClient(create_app(schedule_service_factory=lambda: fake_service))

    response = client.post(
        "/api/v1/schedules/daily",
        json={
            "schedule_id": "daily",
            "name": "Daily",
            "trigger_type": "interval",
            "interval_seconds": 3600,
            "run_at": "2026-05-11T00:00:00Z",
            "profile": "live-offline",
            "topic": "AI policy",
            "source_limit": 2,
        },
    )
    payload = response.json()
    record = fake_service.upserted_record

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["schedule_id"] == "daily"
    assert record.spec.schedule_id == "daily"
    assert record.spec.interval_seconds == 3600
    assert record.spec.payload_template == {
        "profile": "live-offline",
        "topic": "AI policy",
        "source_limit": 2,
    }


def test_schedule_api_upserts_paper_ingest_interval_schedule() -> None:
    fake_service = _FakeScheduleService()
    client = TestClient(create_app(schedule_service_factory=lambda: fake_service))

    response = client.post(
        "/api/v1/schedules/papers/ingest",
        json={
            "schedule_id": "papers-ingest",
            "name": "Papers ingest",
            "trigger_type": "interval",
            "interval_seconds": 21600,
            "run_at": "2026-05-11T00:00:00Z",
            "candidate_limit": 80,
            "min_github_stars": 25,
            "queue_name": "news:queue:papers",
        },
    )
    payload = response.json()
    call = fake_service.paper_ingest_calls[0]

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["schedule_id"] == "papers-ingest"
    assert call["schedule_id"] == "papers-ingest"
    assert call["interval_seconds"] == 21600
    assert call["run_at"].isoformat().replace("+00:00", "Z") == "2026-05-11T00:00:00Z"
    assert call["candidate_limit"] == 80
    assert call["min_github_stars"] == 25
    assert call["queue_name"] == "news:queue:papers"


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
        self.paper_ingest_calls = []
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

    def upsert_daily_schedule(self, **kwargs):
        from framework.workers import ScheduleRecord, ScheduleSpec

        record = ScheduleRecord(
            spec=ScheduleSpec(
                schedule_id=kwargs["schedule_id"],
                name=kwargs["name"],
                trigger_type=kwargs["trigger_type"],
                task_type="daily_intelligence.run",
                payload_template={
                    "profile": kwargs["profile"],
                    "topic": kwargs["topic"],
                    "source_limit": kwargs["source_limit"],
                },
                queue_name=kwargs["queue_name"],
                interval_seconds=kwargs["interval_seconds"],
                run_at=kwargs["run_at"],
            )
        )
        self.upserted_record = record
        return _Result({"schedule_id": record.schedule_id, "schedule": record.to_dict()})

    def upsert_paper_ingest_schedule(self, **kwargs):
        self.paper_ingest_calls.append(kwargs)
        return _Result(
            {
                "schedule_id": kwargs["schedule_id"],
                "schedule": {
                    "spec": {
                        "schedule_id": kwargs["schedule_id"],
                        "trigger_type": kwargs["trigger_type"],
                        "task_type": "papers.ingest_github_arxiv_daily",
                        "queue_name": kwargs["queue_name"],
                        "payload_template": {
                            "candidate_limit": kwargs["candidate_limit"],
                            "min_github_stars": kwargs["min_github_stars"],
                        },
                    }
                },
            }
        )

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
