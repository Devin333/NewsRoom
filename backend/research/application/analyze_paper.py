from __future__ import annotations

from backend.research.domain.analysis import ResearchAnalysis
from backend.research.application.single_paper_runtime import (
    AnalyzePaperRequest,
    ResearchAnalysisResult,
    ResearchDynamicTaskPlanUnavailableError,
    ResearchSinglePaperRuntime,
)


class AnalyzePaperUseCase:
    def __init__(self, runtime: ResearchSinglePaperRuntime | None = None) -> None:
        self._runtime = runtime

    def analyze(self, request: AnalyzePaperRequest) -> ResearchAnalysisResult:
        if self._runtime is None:
            raise ValueError("AnalyzePaperUseCase requires a ResearchSinglePaperRuntime")
        return self._runtime.run(request)

    def accept_modeled_analysis(self, analysis: ResearchAnalysis) -> ResearchAnalysis:
        return analysis


__all__ = [
    "AnalyzePaperRequest",
    "AnalyzePaperUseCase",
    "ResearchAnalysisResult",
    "ResearchDynamicTaskPlanUnavailableError",
]
