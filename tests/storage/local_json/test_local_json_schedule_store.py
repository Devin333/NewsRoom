from datetime import UTC, datetime

import pytest

from core.framework.workers import ScheduleNotFoundError, ScheduleRecord, ScheduleSpec
from storage.local_json import LocalJsonScheduleStore


def test_local_json_schedule_store_persists_records(tmp_path) -> None:
    path = tmp_path / "schedules.json"
    store = LocalJsonScheduleStore(path)
    record = ScheduleRecord(
        spec=ScheduleSpec(
            schedule_id="daily",
            name="Daily",
            trigger_type="interval",
            task_type="daily_intelligence.run",
            payload_template={"topic": "AI"},
            interval_seconds=3600,
        ),
        last_run_at=_dt("2026-05-11T00:00:00Z"),
    )

    store.upsert_schedule(record)
    restored = LocalJsonScheduleStore(path).get_schedule("daily")

    assert restored.schedule_id == "daily"
    assert restored.spec.payload_template == {"topic": "AI"}
    assert restored.last_run_at == _dt("2026-05-11T00:00:00Z")


def test_local_json_schedule_store_updates_state_and_filters_enabled(tmp_path) -> None:
    store = LocalJsonScheduleStore(tmp_path / "schedules.json")
    store.upsert_schedule(_record("daily"))
    store.upsert_schedule(_record("disabled", enabled=False))

    updated = store.update_run_state(
        "daily",
        last_run_at=_dt("2026-05-11T01:00:00Z"),
        next_run_at=_dt("2026-05-11T02:00:00Z"),
    )
    enabled = store.list_schedules(enabled_only=True)

    assert updated.last_run_at == _dt("2026-05-11T01:00:00Z")
    assert updated.next_run_at == _dt("2026-05-11T02:00:00Z")
    assert [record.schedule_id for record in enabled] == ["daily"]


def test_local_json_schedule_store_deletes_records(tmp_path) -> None:
    store = LocalJsonScheduleStore(tmp_path / "schedules.json")
    store.upsert_schedule(_record("daily"))

    assert store.delete_schedule("daily") is True
    assert store.delete_schedule("daily") is False
    with pytest.raises(ScheduleNotFoundError):
        store.get_schedule("daily")


def _record(schedule_id: str, *, enabled: bool = True) -> ScheduleRecord:
    return ScheduleRecord(
        spec=ScheduleSpec(
            schedule_id=schedule_id,
            name=schedule_id.title(),
            trigger_type="interval",
            task_type="daily_intelligence.run",
            interval_seconds=3600,
            enabled=enabled,
        )
    )


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
