from __future__ import annotations

from datetime import UTC, datetime

from framework.harness.control_plane import (
    HarnessEvent,
    HarnessEventType,
    transcript_entry_from_event,
)


def test_budget_fact_event_projects_only_bounded_fact_ref_into_transcript() -> None:
    event = HarnessEvent(
        event_type=HarnessEventType.BUDGET_FACT_RECORDED,
        run_id="run-transcript-budget",
        node_id="step-1",
        payload={
            "resolution_status": "verified",
            "operation_id": "operation-1",
            "ledger_revision": 2,
            "within_budget": True,
            "violations": [],
            "fact_ref": "sha256:" + "a" * 64,
            "event_id": "budget-event-2",
            "event_type": "budget_reservation_settled",
            "reservation_id": "reservation-1",
            "policy_digest": "sha256:" + "b" * 64,
            "scope_id": "run-transcript-budget:root",
            "stream_sequence": 2,
        },
        occurred_at=datetime(2026, 8, 12, tzinfo=UTC),
    )

    entry = transcript_entry_from_event(event)

    assert entry.phase == "VERIFY"
    assert entry.input_refs == ("sha256:" + "a" * 64,)
    assert entry.budget_snapshot is not None
    assert entry.budget_snapshot["operation_id"] == "operation-1"
    assert "raw_prompt" not in str(entry.to_dict())
