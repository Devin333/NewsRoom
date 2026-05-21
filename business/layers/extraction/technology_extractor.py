from __future__ import annotations

from business.foundation import AnalysisContext, Signal, Technology
from business.layers.extraction.pipeline import ExtractionPipeline


class TechnologyExtractor:
    def extract(self, signal: Signal, context: AnalysisContext | None = None) -> list[Technology]:
        return ExtractionPipeline().extract(signal, context or AnalysisContext(board_type=signal.board_type)).technologies
