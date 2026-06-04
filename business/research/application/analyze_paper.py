from __future__ import annotations

from business.research.domain.analysis import ResearchAnalysis


class AnalyzePaperUseCase:
    def accept_modeled_analysis(self, analysis: ResearchAnalysis) -> ResearchAnalysis:
        return analysis


__all__ = ["AnalyzePaperUseCase"]
