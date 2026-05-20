from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from framework.events import Event, EventEnvelope, EventFilter, EventType


@dataclass(frozen=True)
class _Window:
    start: datetime
    end: datetime


def test_event_and_envelope_round_trip_and_sequence() -> None:
    event = Event(
        event_type=EventType.WORKFLOW_STARTED,
        payload={"run_id": "run-1"},
        source="workflow",
        created_at=datetime(2026, 5, 20, 1, 2, tzinfo=UTC),
    )
    envelope = EventEnvelope(
        event_id="evt-1",
        event=event,
        correlation_id="run-1",
    ).with_sequence(7)

    restored = EventEnvelope.from_dict(envelope.to_dict())

    assert restored.event.event_type == "workflow_started"
    assert restored.sequence == 7
    assert restored.to_dict()["event"]["created_at"] == "2026-05-20T01:02:00Z"


def test_event_filter_matches_type_source_correlation_and_time_window() -> None:
    created_at = datetime(2026, 5, 20, 1, 0, tzinfo=UTC)
    envelope = EventEnvelope(
        event_id="evt-1",
        event=Event("step_started", source="workflow", created_at=created_at),
        correlation_id="run-1",
    )

    assert EventFilter(
        event_types=["step_started"],
        source="workflow",
        correlation_id="run-1",
        time_window=_Window(
            start=datetime(2026, 5, 20, 0, 0, tzinfo=UTC),
            end=datetime(2026, 5, 20, 2, 0, tzinfo=UTC),
        ),
    ).matches(envelope)
    assert not EventFilter(event_types=["step_finished"]).matches(envelope)
