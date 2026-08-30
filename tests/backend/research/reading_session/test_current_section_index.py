from __future__ import annotations

from backend.research.reading_session import ReadingEvent, ReadingSession
from tests.backend.research.helpers import FIXED_NOW


def _event(event_id: str, event_type: str, *, section_index: int | None = None) -> ReadingEvent:
    metadata = {} if section_index is None else {"section_index": section_index}
    return ReadingEvent(
        event_id=event_id,
        event_type=event_type,  # type: ignore[arg-type]
        paper_id="paper-1",
        user_id="user-1",
        created_at=FIXED_NOW,
        metadata=metadata,
    )


def _session(events: list[ReadingEvent]) -> ReadingSession:
    return ReadingSession(
        session_id="session-1",
        paper_id="paper-1",
        user_id="user-1",
        events=events,
        source_refs=["paper://paper-1"],
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
    )


def test_no_section_selected_defaults_to_zero():
    session = _session([_event("e1", "highlight_created")])
    assert session.current_section_index() == 0


def test_empty_session_defaults_to_zero():
    assert _session([]).current_section_index() == 0


def test_returns_latest_section_selected():
    session = _session([
        _event("e1", "section_selected", section_index=2),
        _event("e2", "highlight_created"),
        _event("e3", "section_selected", section_index=5),
    ])
    assert session.current_section_index() == 5


def test_section_selected_without_index_skipped():
    session = _session([
        _event("e1", "section_selected", section_index=3),
        _event("e2", "section_selected"),  # no section_index → skip, keep scanning back
    ])
    assert session.current_section_index() == 3


def test_invalid_section_index_skipped():
    session = _session([
        _event("e1", "section_selected", section_index=4),
        _event("e2", "section_selected", section_index="not-a-number"),  # type: ignore[arg-type]
    ])
    assert session.current_section_index() == 4


def test_negative_section_index_clamped_to_zero():
    session = _session([_event("e1", "section_selected", section_index=-3)])
    assert session.current_section_index() == 0
