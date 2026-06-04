from __future__ import annotations

from typing import Protocol, runtime_checkable

from business.research.domain.evidence import ResearchEvidencePack
from business.research.domain.paper import ResearchPaper
from business.research.paper_card.models import ResearchPaperCard
from business.research.reading_session.models import ReadingNote, ReadingSession


@runtime_checkable
class ResearchPaperRepository(Protocol):
    def get(self, paper_id: str) -> ResearchPaper | None:
        ...

    def save(self, paper: ResearchPaper) -> None:
        ...


@runtime_checkable
class PaperCardRepository(Protocol):
    def save(self, card: ResearchPaperCard) -> None:
        ...


@runtime_checkable
class EvidencePackRepository(Protocol):
    def save(self, evidence_pack: ResearchEvidencePack) -> None:
        ...


@runtime_checkable
class ReadingSessionRepository(Protocol):
    def get(self, session_id: str) -> ReadingSession | None:
        ...

    def save_note(self, note: ReadingNote) -> None:
        ...


__all__ = [
    "EvidencePackRepository",
    "PaperCardRepository",
    "ReadingSessionRepository",
    "ResearchPaperRepository",
]
