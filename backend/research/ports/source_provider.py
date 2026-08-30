from __future__ import annotations

from typing import Protocol, runtime_checkable

from backend.research.domain.paper import PaperSourceRecord, ResearchPaper


@runtime_checkable
class PaperSourceProvider(Protocol):
    def fetch_paper(self, source_url: str) -> ResearchPaper:
        ...

    def fetch_source_record(self, paper_id: str) -> PaperSourceRecord:
        ...


__all__ = ["PaperSourceProvider"]
