from __future__ import annotations

from business.research.domain.paper import ResearchPaper
from business.research.paper_card.models import ResearchPaperCard
from business.research.paper_card.service import PaperCardBuilder


class BuildPaperCardUseCase:
    def __init__(self, builder: PaperCardBuilder | None = None) -> None:
        self._builder = builder or PaperCardBuilder()

    def build(self, paper: ResearchPaper) -> ResearchPaperCard:
        return self._builder.build(paper=paper)


__all__ = ["BuildPaperCardUseCase"]
