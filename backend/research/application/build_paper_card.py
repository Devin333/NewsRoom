from __future__ import annotations

from backend.research.domain.paper import ResearchPaper
from backend.research.paper_card.models import ResearchPaperCard
from backend.research.paper_card.service import PaperCardBuilder


class BuildPaperCardUseCase:
    def __init__(self, builder: PaperCardBuilder | None = None) -> None:
        self._builder = builder or PaperCardBuilder()

    def build(self, paper: ResearchPaper) -> ResearchPaperCard:
        return self._builder.build(paper=paper)


__all__ = ["BuildPaperCardUseCase"]
