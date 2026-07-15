from __future__ import annotations

import pytest

from framework.harness import HarnessEventLogEntry, InMemoryHarnessEventLog


def test_event_log_is_append_only_and_exports_dict() -> None:
    log = InMemoryHarnessEventLog()
    entry = HarnessEventLogEntry(
        event_id="event-1",
        run_id="run-event",
        step_id="collect",
        event_type="phase_recorded",
        metadata={"phase": "plan", "budget_snapshot": {"turns_used": 1}},
    )

    log.append(entry)

    assert log.entries_for_run("run-event") == (entry,)
    assert log.to_dict()["events"][0]["event_id"] == "event-1"
    try:
        log.append(entry)
    except Exception as exc:
        assert exc.__class__.__name__ == "HarnessValidationError"
    else:
        raise AssertionError("expected HarnessValidationError")


def test_event_log_entry_detaches_and_deeply_freezes_projection_content() -> None:
    decision = {"decision_type": "retry_step", "payload": {"attempt": 1}}
    metadata = {"gate": {"details": ["bounded"]}}
    entry = HarnessEventLogEntry(
        event_id="event-immutable",
        run_id="run-event",
        event_type="decision_recorded",
        decision=decision,
        metadata=metadata,
    )

    decision["payload"]["attempt"] = 99
    metadata["gate"]["details"].append("mutated")

    assert entry.decision["payload"]["attempt"] == 1
    assert entry.metadata["gate"]["details"] == ("bounded",)
    with pytest.raises(TypeError):
        entry.decision["payload"]["attempt"] = 2  # type: ignore[index]
    with pytest.raises(TypeError):
        entry.metadata["gate"] = {}  # type: ignore[index]
