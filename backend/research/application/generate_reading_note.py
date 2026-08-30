from __future__ import annotations

from backend.research.reading_session.models import ReadingNote, ReadingSession
from backend.research.reading_session.notes import ReadingNoteService


class GenerateReadingNoteUseCase:
    def __init__(self, service: ReadingNoteService | None = None) -> None:
        self._service = service or ReadingNoteService()

    def generate(
        self,
        *,
        reading_note_id: str,
        session: ReadingSession,
        generated_summary: str,
        selected_event_ids: list[str],
    ) -> ReadingNote:
        return self._service.build_note_from_selection(
            reading_note_id=reading_note_id,
            session=session,
            generated_summary=generated_summary,
            selected_event_ids=selected_event_ids,
        )


__all__ = ["GenerateReadingNoteUseCase"]
