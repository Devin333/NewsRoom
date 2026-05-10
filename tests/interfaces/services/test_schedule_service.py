from datetime import UTC, datetime

from core.framework.workers import (
    InMemoryScheduleStore,
    ScheduleRecord,
    ScheduleSpec,
    TaskStatus,
)
from interfaces.services.schedule_service import ScheduleApplicationService


def test_schedule_service_lists_enabled_schedules() -> None:
    service = ScheduleApplicationService(
        store=InMemoryScheduleStore([_record("daily"), _record("disabled", enabled=False)]),
        queue=_FakeQueue(),
    )

    result = service.list_schedules(enabled_only=True)

    assert result.to_dict()["schedule_count"] == 1
    assert result.schedules[0].schedule_id == "daily"


def test_schedule_service_tick_enqueues_due_schedule_and_updates_state() -> None:
    store = InMemoryScheduleStore(
        [
            _record(
                "daily",
                last_run_at=_dt("2026-05-11T00:00:00Z"),
                interval_seconds=3600,
            )
        ]
    )
    queue = _FakeQueue()
    service = ScheduleApplicationService(store=store, queue=queue)

    result = service.tick(now=_dt("2026-05-11T01:00:00Z"))

    payload = result.to_dict()
    assert payload["enqueued_count"] == 1
    assert payload["state_updates"] == {"daily": "2026-05-11T01:00:00Z"}
    assert store.get_schedule("daily").last_run_at == _dt("2026-05-11T01:00:00Z")
    assert store.get_schedule("daily").next_run_at == _dt("2026-05-11T02:00:00Z")
    assert queue.enqueued[0].metadata["schedule_id"] == "daily"
    assert queue.enqueued[0].status == TaskStatus.QUEUED


def test_schedule_service_tick_persists_skipped_misfire_state() -> None:
    store = InMemoryScheduleStore(
        [
            _record(
                "source-health",
                last_run_at=_dt("2026-05-11T00:00:00Z"),
                interval_seconds=600,
                misfire_policy="skip",
            )
        ]
    )
    queue = _FakeQueue()
    service = ScheduleApplicationService(store=store, queue=queue)

    result = service.tick(now=_dt("2026-05-11T00:35:00Z"))

    payload = result.to_dict()
    assert payload["enqueued_count"] == 0
    assert payload["evaluations"][0]["reason"] == "misfire_skipped"
    assert store.get_schedule("source-health").last_run_at == _dt("2026-05-11T00:30:00Z")
    assert store.get_schedule("source-health").next_run_at == _dt("2026-05-11T00:40:00Z")
    assert queue.enqueued == []


def test_schedule_service_manual_trigger_enqueues_and_updates_state() -> None:
    store = InMemoryScheduleStore([_manual_record("manual-daily")])
    queue = _FakeQueue()
    service = ScheduleApplicationService(store=store, queue=queue)

    result = service.trigger_manual("manual-daily", now=_dt("2026-05-11T01:05:00Z"))

    payload = result.to_dict()
    assert payload["schedule_id"] == "manual-daily"
    assert payload["enqueued"]["message_id"] == "msg-1"
    assert store.get_schedule("manual-daily").last_run_at == _dt("2026-05-11T01:05:00Z")
    assert queue.enqueued[0].payload == {"topic": "AI"}


class _FakeQueue:
    def __init__(self) -> None:
        self.enqueued = []

    def enqueue(self, task):
        task.status = TaskStatus.QUEUED
        self.enqueued.append(task)
        return f"msg-{len(self.enqueued)}"


def _record(
    schedule_id: str,
    *,
    enabled: bool = True,
    last_run_at=None,
    interval_seconds: int = 3600,
    misfire_policy: str = "run_once",
) -> ScheduleRecord:
    return ScheduleRecord(
        spec=ScheduleSpec(
            schedule_id=schedule_id,
            name=schedule_id.title(),
            trigger_type="interval",
            task_type="daily_intelligence.run",
            payload_template={"topic": "AI"},
            interval_seconds=interval_seconds,
            enabled=enabled,
            misfire_policy=misfire_policy,
        ),
        last_run_at=last_run_at,
    )


def _manual_record(schedule_id: str) -> ScheduleRecord:
    return ScheduleRecord(
        spec=ScheduleSpec(
            schedule_id=schedule_id,
            name=schedule_id.title(),
            trigger_type="manual",
            task_type="daily_intelligence.run",
            payload_template={"topic": "AI"},
        )
    )


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
