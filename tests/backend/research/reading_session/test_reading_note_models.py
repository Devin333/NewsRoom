from __future__ import annotations

from backend.research.reading_session import (
    ReadingEvent,
    ReadingNoteService,
    ReadingSession,
    validate_reading_note_source_refs,
    validate_reading_note_user_selection_refs,
    validate_session_owner,
)
from tests.backend.research.helpers import FIXED_NOW


def test_reading_note_requires_user_selection_and_source_refs() -> None:
    event = ReadingEvent(
        event_id="event-1",
        event_type="highlight_created",
        paper_id="paper-1",
        user_id="user-1",
        text="Harness controls publication.",
        source_refs=["paper://paper-1/sec-intro"],
        created_at=FIXED_NOW,
    )
    session = ReadingSession(
        session_id="session-1",
        paper_id="paper-1",
        user_id="user-1",
        events=[event],
        selected_refs=["event-1"],
        source_refs=["paper://paper-1"],
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
    )

    note = ReadingNoteService().build_note_from_selection(
        reading_note_id="note-1",
        session=session,
        generated_summary="Harness-owned flow prevents private memory leakage.",
        selected_event_ids=["event-1"],
        key_takeaways=["Keep gates deterministic"],
    )

    assert note.to_dict()["user_selection_refs"] == ["event-1"]
    assert "paper://paper-1/sec-intro" in note.source_refs
    assert validate_reading_note_source_refs(note).passed is True
    assert validate_reading_note_user_selection_refs(note).passed is True
    assert validate_session_owner(session, user_id="user-1").passed is True
    assert validate_session_owner(session, user_id="user-2").passed is False
