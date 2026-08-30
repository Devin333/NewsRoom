from __future__ import annotations

from backend.research.application import GenerateReadingNoteUseCase
from backend.research.reading_session import ReadingEvent, ReadingSession
from tests.backend.research.helpers import FIXED_NOW


def test_generate_reading_note_use_case_uses_user_selection_refs() -> None:
    session = ReadingSession(
        session_id="session-1",
        paper_id="paper-1",
        user_id="user-1",
        events=[
            ReadingEvent(
                event_id="event-highlight",
                event_type="highlight_created",
                paper_id="paper-1",
                user_id="user-1",
                text="Harness controls publication.",
                source_refs=["paper://paper-1/sec-intro"],
                created_at=FIXED_NOW,
            )
        ],
        source_refs=["paper://paper-1"],
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
    )

    note = GenerateReadingNoteUseCase().generate(
        reading_note_id="note-1",
        session=session,
        generated_summary="The user selected a Harness control claim.",
        selected_event_ids=["event-highlight"],
    )

    assert note.user_selection_refs == ["event-highlight"]
    assert "paper://paper-1/sec-intro" in note.source_refs
