from __future__ import annotations

from datetime import UTC, datetime

from backend.research.reading_session.models import ReadingNote, ReadingSession


class ReadingNoteService:
    def build_note_from_selection(
        self,
        *,
        reading_note_id: str,
        session: ReadingSession,
        generated_summary: str,
        selected_event_ids: list[str],
        key_takeaways: list[str] | None = None,
        method_notes: list[str] | None = None,
        benchmark_notes: list[str] | None = None,
        open_questions: list[str] | None = None,
    ) -> ReadingNote:
        selected = [event for event in session.events if event.event_id in set(selected_event_ids)]
        source_refs: list[str] = list(session.source_refs)
        highlights: list[str] = []
        notes: list[str] = []
        questions: list[str] = []
        for event in selected:
            source_refs.extend(event.source_refs)
            if event.event_type == "highlight_created" and event.text:
                highlights.append(event.text)
            elif event.event_type == "note_created" and event.text:
                notes.append(event.text)
            elif event.event_type == "question_asked" and event.text:
                questions.append(event.text)
        return ReadingNote(
            reading_note_id=reading_note_id,
            paper_id=session.paper_id,
            user_id=session.user_id,
            selected_highlights=highlights,
            selected_notes=notes,
            selected_questions=questions,
            generated_summary=generated_summary,
            key_takeaways=key_takeaways or [],
            method_notes=method_notes or [],
            benchmark_notes=benchmark_notes or [],
            open_questions=open_questions or [],
            source_refs=source_refs,
            user_selection_refs=selected_event_ids,
            created_at=datetime.now(UTC),
        )


__all__ = ["ReadingNoteService"]
