from __future__ import annotations

from business.foundation import AnalysisContext, Entity, Signal
from business.layers.extraction.pipeline import ExtractionPipeline


class EntityExtractor:
    def extract(self, signal: Signal, context: AnalysisContext | None = None) -> list[Entity]:
        return ExtractionPipeline().extract(signal, context or AnalysisContext(board_type=signal.board_type)).entities
