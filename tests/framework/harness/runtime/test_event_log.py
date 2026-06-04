from __future__ import annotations

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
