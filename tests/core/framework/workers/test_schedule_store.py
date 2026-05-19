from datetime import UTC, datetime

import pytest

from core.framework.workers import (
    InMemoryScheduleStore,
    ScheduleNotFoundError,
    ScheduleRecord,
    ScheduleSpec,
)


def test_schedule_spec_round_trips_json_safe_dict() -> None:
    spec = ScheduleSpec(
        schedule_id="daily",
        name="Daily",
        trigger_type="interval",
        task_type="daily_intelligence.run",
        payload_template={"topic": "AI"},
        interval_seconds=3600,
        run_at=_dt("2026-05-11T00:00:00Z"),
        misfire_policy="run_once",
        metadata={"owner": "ops"},
    )

    payload = spec.to_dict()
    restored = ScheduleSpec.from_dict(payload)

    assert payload["trigger_config"]["run_at"] == "2026-05-11T00:00:00Z"
    assert restored.schedule_id == "daily"
    assert restored.interval_seconds == 3600
    assert restored.run_at == _dt("2026-05-11T00:00:00Z")
    assert restored.payload_template == {"topic": "AI"}
    assert restored.metadata == {"owner": "ops"}


def test_schedule_record_round_trips_state() -> None:
    record = ScheduleRecord(
        spec=_schedule("daily"),
        last_run_at=_dt("2026-05-11T00:00:00Z"),
        next_run_at=_dt("2026-05-11T01:00:00Z"),
        last_misfire_reason="catchup_bounded",
        last_evaluation_at=_dt("2026-05-11T00:30:00Z"),
        created_at=_dt("2026-05-10T00:00:00Z"),
        updated_at=_dt("2026-05-11T00:00:00Z"),
    )

    restored = ScheduleRecord.from_dict(record.to_dict())

    assert restored.schedule_id == "daily"
    assert restored.last_run_at == _dt("2026-05-11T00:00:00Z")
    assert restored.next_run_at == _dt("2026-05-11T01:00:00Z")
    assert restored.last_misfire_reason == "catchup_bounded"
    assert restored.last_evaluation_at == _dt("2026-05-11T00:30:00Z")
    assert restored.created_at == _dt("2026-05-10T00:00:00Z")


def test_in_memory_schedule_store_lists_enabled_only_and_updates_state() -> None:
    store = InMemoryScheduleStore(
        [_record("daily"), _record("disabled", enabled=False)],
        now_fn=lambda: _dt("2026-05-11T01:01:00Z"),
    )

    enabled = store.list_schedules(enabled_only=True)
    updated = store.update_run_state(
        "daily",
        last_run_at=_dt("2026-05-11T01:00:00Z"),
        next_run_at=_dt("2026-05-11T02:00:00Z"),
        last_misfire_reason="catch_up",
        last_evaluation_at=_dt("2026-05-11T01:01:00Z"),
    )

    assert [record.schedule_id for record in enabled] == ["daily"]
    assert updated.last_run_at == _dt("2026-05-11T01:00:00Z")
    assert updated.next_run_at == _dt("2026-05-11T02:00:00Z")
    assert updated.last_misfire_reason == "catch_up"
    assert updated.last_evaluation_at == _dt("2026-05-11T01:01:00Z")
    assert updated.updated_at == _dt("2026-05-11T01:01:00Z")
    fetched = store.get_schedule("daily")
    assert fetched.last_run_at == _dt("2026-05-11T01:00:00Z")
    assert fetched.last_misfire_reason == "catch_up"


def test_in_memory_schedule_store_delete_and_missing() -> None:
    store = InMemoryScheduleStore([_record("daily")])

    assert store.delete_schedule("daily") is True
    assert store.delete_schedule("daily") is False
    with pytest.raises(ScheduleNotFoundError):
        store.get_schedule("daily")


def _record(schedule_id: str, *, enabled: bool = True) -> ScheduleRecord:
    return ScheduleRecord(spec=_schedule(schedule_id, enabled=enabled))


def _schedule(schedule_id: str, *, enabled: bool = True) -> ScheduleSpec:
    return ScheduleSpec(
        schedule_id=schedule_id,
        name=schedule_id.title(),
        trigger_type="interval",
        task_type="daily_intelligence.run",
        interval_seconds=3600,
        enabled=enabled,
    )


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
