from __future__ import annotations

from datetime import timedelta

from framework.governance.audit import AuditEvent, AuditRecorder, InMemoryAuditStore
from framework.shared.time import utc_now


def test_audit_event_round_trips_to_dict() -> None:
    event = AuditEvent(action="tool.run", actor="agent", target="search", payload={"ok": True})

    restored = AuditEvent.from_dict(event.to_dict())

    assert restored.event_id == event.event_id
    assert restored.action == "tool.run"
    assert restored.payload == {"ok": True}


def test_in_memory_audit_store_filters_events() -> None:
    store = InMemoryAuditStore()
    now = utc_now()
    store.append(AuditEvent(action="a", actor="one", target="x", occurred_at=now))
    store.append(AuditEvent(action="b", actor="two", target="y", occurred_at=now + timedelta(seconds=10)))

    assert [event.action for event in store.list({"actor": "one"})] == ["a"]
    assert [event.action for event in store.list({"since": now + timedelta(seconds=1)})] == ["b"]
    store.clear()
    assert store.list() == []


def test_audit_recorder_records_events() -> None:
    recorder = AuditRecorder()

    event = recorder.record("policy.check", actor="runner", payload={"allowed": True})

    assert recorder.list_events() == [event]
