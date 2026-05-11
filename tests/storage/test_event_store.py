import asyncio
from datetime import UTC, datetime

import pytest

from storage.events import EventRecord, LocalJsonEventStore


def _event(
    event_id: str,
    *,
    step_id: str | None = None,
    timestamp: datetime | None = None,
    severity: str = "info",
) -> EventRecord:
    return EventRecord(
        event_id=event_id,
        run_id="run-1",
        workflow_id="daily",
        step_id=step_id,
        event_type="workflow_step_completed",
        timestamp=timestamp or datetime(2026, 5, 11, 1, 0, tzinfo=UTC),
        payload={"status": "ok"},
        severity=severity,
        trace_id="trace-1",
        redacted=True,
        metadata={"source": "test"},
    )


def test_event_record_round_trips() -> None:
    event = _event("event-1", step_id="draft_report", severity="warning")

    restored = EventRecord.from_dict(event.to_dict())

    assert restored == event
    assert restored.to_dict()["timestamp"] == "2026-05-11T01:00:00Z"


def test_event_record_accepts_legacy_occurred_at() -> None:
    payload = _event("event-1").to_dict()
    payload["occurred_at"] = payload.pop("timestamp")

    restored = EventRecord.from_dict(payload)

    assert restored.timestamp == datetime(2026, 5, 11, 1, 0, tzinfo=UTC)


def test_event_record_rejects_invalid_severity() -> None:
    with pytest.raises(ValueError, match="invalid severity"):
        _event("event-1", severity="notice")


def test_local_json_event_store_appends_and_lists_by_run(tmp_path) -> None:
    store = LocalJsonEventStore(tmp_path)
    first = _event("event-1", timestamp=datetime(2026, 5, 11, 1, 0, tzinfo=UTC))
    second = _event("event-2", timestamp=datetime(2026, 5, 11, 2, 0, tzinfo=UTC))

    assert store.append_event(first) == 0
    assert store.append_event(second) == 1

    assert store.list_by_run("run-1") == [first, second]
    assert store.list_by_run("run-1", limit=1) == [first]


def test_local_json_event_store_lists_by_step_and_streams_from_offset(tmp_path) -> None:
    store = LocalJsonEventStore(tmp_path)
    first = _event("event-1", step_id="collect_sources")
    second = _event("event-2", step_id="draft_report")
    third = _event("event-3", step_id="draft_report")
    for event in [first, second, third]:
        store.append_event(event)

    assert store.list_by_step("run-1", "draft_report") == [second, third]

    async def collect() -> list[EventRecord]:
        return [event async for event in store.stream_from_offset("run-1", 1)]

    assert asyncio.run(collect()) == [second, third]


def test_local_json_event_store_handles_missing_and_rejects_invalid_inputs(tmp_path) -> None:
    store = LocalJsonEventStore(tmp_path)

    assert store.list_by_run("missing") == []

    with pytest.raises(ValueError, match="limit must be greater than zero"):
        store.list_by_run("run-1", limit=0)

    with pytest.raises(ValueError, match="invalid run_id"):
        store.list_by_run("../secret")

    with pytest.raises(ValueError, match="invalid step_id"):
        store.append_event(_event("event-1", step_id="../secret"))

    async def collect_invalid_offset() -> list[EventRecord]:
        return [event async for event in store.stream_from_offset("run-1", -1)]

    with pytest.raises(ValueError, match="offset must be greater than or equal to zero"):
        asyncio.run(collect_invalid_offset())
