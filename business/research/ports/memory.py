from __future__ import annotations

from typing import Protocol, runtime_checkable

from business.research.reading_session.models import ReadingNote


@runtime_checkable
class ResearchMemoryPort(Protocol):
    def write_reading_note(self, note: ReadingNote, *, namespace: str) -> str:
        ...


__all__ = ["ResearchMemoryPort"]
