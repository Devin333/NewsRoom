from datetime import UTC, datetime

import pytest

from framework.workers import ScheduleNotFoundError, ScheduleRecord, ScheduleSpec
from infrastructure.storage.local_json import LocalJsonScheduleStore


def test_local_json_schedule_store_persists_records(tmp_path) -> None:
    path = tmp_path / "schedules.json"
    store = LocalJsonScheduleStore(path)
    record = ScheduleRecord(
        spec=ScheduleSpec(
            schedule_id="memory-reindex",
            name="Memory Reindex",
            trigger_type="interval",
            task_type="memory.reindex",
            payload_template={"run_id": "run-1"},
            queue_name="news:queue:memory",
            interval_seconds=3600,
        ),
        last_run_at=_dt("2026-05-11T00:00:00Z"),
    )

    store.upsert_schedule(record)
    restored = LocalJsonScheduleStore(path).get_schedule("memory-reindex")

    assert restored.schedule_id == "memory-reindex"
    assert restored.spec.payload_template == {"run_id": "run-1"}
    assert restored.last_run_at == _dt("2026-05-11T00:00:00Z")


def test_local_json_schedule_store_updates_state_and_filters_enabled(tmp_path) -> None:
    store = LocalJsonScheduleStore(tmp_path / "schedules.json")
    store.upsert_schedule(_record("memory-reindex"))
    store.upsert_schedule(_record("disabled", enabled=False))

    updated = store.update_run_state(
        "memory-reindex",
        last_run_at=_dt("2026-05-11T01:00:00Z"),
        next_run_at=_dt("2026-05-11T02:00:00Z"),
    )
    enabled = store.list_schedules(enabled_only=True)

    assert updated.last_run_at == _dt("2026-05-11T01:00:00Z")
    assert updated.next_run_at == _dt("2026-05-11T02:00:00Z")
    assert [record.schedule_id for record in enabled] == ["memory-reindex"]


def test_local_json_schedule_store_deletes_records(tmp_path) -> None:
    store = LocalJsonScheduleStore(tmp_path / "schedules.json")
    store.upsert_schedule(_record("memory-reindex"))

    assert store.delete_schedule("memory-reindex") is True
    assert store.delete_schedule("memory-reindex") is False
    with pytest.raises(ScheduleNotFoundError):
        store.get_schedule("memory-reindex")


def _record(schedule_id: str, *, enabled: bool = True) -> ScheduleRecord:
    return ScheduleRecord(
        spec=ScheduleSpec(
            schedule_id=schedule_id,
            name=schedule_id.title(),
            trigger_type="interval",
            task_type="memory.reindex",
            queue_name="news:queue:memory",
            interval_seconds=3600,
            enabled=enabled,
        )
    )


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
