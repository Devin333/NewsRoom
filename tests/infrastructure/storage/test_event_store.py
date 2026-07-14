import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from framework.artifacts import ArtifactPathError
from infrastructure.storage.events import EventRecord, LocalJsonEventStore
from infrastructure.storage.security import REDACTED_VALUE


def _event(
    event_id: str,
    *,
    step_id: str | None = None,
    event_type: str = "workflow_step_completed",
    timestamp: datetime | None = None,
    severity: str = "info",
) -> EventRecord:
    return EventRecord(
        event_id=event_id,
        run_id="run-1",
        workflow_id="daily",
        step_id=step_id,
        event_type=event_type,
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


def test_local_json_event_store_preserves_logical_event_id(tmp_path) -> None:
    store = LocalJsonEventStore(tmp_path)
    event = _event("agent:step:event-1")

    store.append_event(event)

    assert store.list_by_run("run-1") == [event]


@pytest.mark.parametrize("run_id", ["../secret", "run:stream", "CON", " run-1"])
def test_local_json_event_store_rejects_unsafe_run_id_without_side_effect(
    tmp_path,
    run_id: str,
) -> None:
    store = LocalJsonEventStore(tmp_path)

    with pytest.raises(ArtifactPathError):
        store.append_event(replace(_event("event:logical"), run_id=run_id))

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("step_id", ["../secret", "step:stream", "CON", " step-1"])
def test_local_json_event_store_rejects_unsafe_step_id_without_side_effect(
    tmp_path,
    step_id: str,
) -> None:
    store = LocalJsonEventStore(tmp_path)

    with pytest.raises(ArtifactPathError):
        store.append_event(_event("event:logical", step_id=step_id))

    assert list(tmp_path.iterdir()) == []


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


def test_local_json_event_store_filters_by_type(tmp_path) -> None:
    store = LocalJsonEventStore(tmp_path)
    first = _event("event-1", event_type="workflow_started")
    second = _event("event-2", event_type="workflow_step_completed")
    third = _event("event-3", event_type="workflow_started")
    for event in [first, second, third]:
        store.append_event(event)

    assert store.filter_by_type("run-1", "workflow_started") == [first, third]
    assert store.filter_by_type("run-1", "workflow_started", limit=1) == [first]


def test_local_json_event_store_redacts_payload_and_metadata(tmp_path) -> None:
    fake_secret = "sk" + "-eventsecret123456"
    store = LocalJsonEventStore(tmp_path)
    event = EventRecord(
        event_id="event-1",
        run_id="run-1",
        event_type="tool_call_failed",
        timestamp=datetime(2026, 5, 11, 1, 0, tzinfo=UTC),
        payload={"api_key": fake_secret, "message": f"failed with {fake_secret}"},
        metadata={"authorization": f"Bearer {fake_secret}", "safe": "visible"},
    )

    store.append_event(event)
    restored = store.list_by_run("run-1")[0]

    assert restored.redacted is True
    assert restored.payload["api_key"] == REDACTED_VALUE
    assert restored.payload["message"] == f"failed with {REDACTED_VALUE}"
    assert restored.metadata["authorization"] == REDACTED_VALUE
    assert restored.metadata["safe"] == "visible"
    assert restored.metadata["redaction_reports"]
    assert fake_secret not in str(restored.to_dict())




def test_local_json_event_store_retrieval_contract_is_stable(tmp_path) -> None:
    store = LocalJsonEventStore(tmp_path)
    first = _event("event-1", step_id="collect_sources", event_type="workflow_started")
    second = _event("event-2", step_id="draft_report", event_type="workflow_step_completed")
    store.append_event(first)
    store.append_event(second)

    by_run = store.list_by_run("run-1")
    by_step = store.list_by_step("run-1", "draft_report")
    by_type = store.filter_by_type("run-1", "workflow_started")

    assert [event.event_id for event in by_run] == ["event-1", "event-2"]
    assert [event.event_id for event in by_step] == ["event-2"]
    assert [event.event_id for event in by_type] == ["event-1"]
    store = LocalJsonEventStore(tmp_path)

    assert store.list_by_run("missing") == []

    with pytest.raises(ValueError, match="limit must be greater than zero"):
        store.list_by_run("run-1", limit=0)

    with pytest.raises(ValueError, match="limit must be greater than zero"):
        store.filter_by_type("run-1", "workflow_started", limit=0)

    with pytest.raises(ValueError, match="event_type is required"):
        store.filter_by_type("run-1", "")

    with pytest.raises(ValueError, match="invalid run_id"):
        store.list_by_run("../secret")

    with pytest.raises(ValueError, match="invalid step_id"):
        store.append_event(_event("event-1", step_id="../secret"))

    async def collect_invalid_offset() -> list[EventRecord]:
        return [event async for event in store.stream_from_offset("run-1", -1)]

    with pytest.raises(ValueError, match="offset must be greater than or equal to zero"):
        asyncio.run(collect_invalid_offset())
