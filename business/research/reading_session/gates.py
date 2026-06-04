from __future__ import annotations

from business.research.domain.common import GateResult
from business.research.reading_session.models import ReadingNote, ReadingSession


def validate_reading_note_source_refs(note: ReadingNote) -> GateResult:
    if not note.source_refs:
        return GateResult.fail("ReadingNoteSourceGate", "reading note requires source refs")
    return GateResult.pass_("ReadingNoteSourceGate")


def validate_reading_note_user_selection_refs(note: ReadingNote) -> GateResult:
    if not note.user_selection_refs:
        return GateResult.fail("ReadingNoteSelectionGate", "reading note requires user selection refs")
    return GateResult.pass_("ReadingNoteSelectionGate")


def validate_session_owner(session: ReadingSession, *, user_id: str) -> GateResult:
    if session.user_id != user_id:
        return GateResult.fail("ReadingNotePrivacyGate", "reading session belongs to another user")
    return GateResult.pass_("ReadingNotePrivacyGate")


__all__ = [
    "validate_reading_note_source_refs",
    "validate_reading_note_user_selection_refs",
    "validate_session_owner",
]
