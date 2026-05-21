from __future__ import annotations

from business.foundation import AnalysisContext, Signal, Topic
from business.layers.extraction.pipeline import ExtractionPipeline


class TopicExtractor:
    def extract(self, signal: Signal, context: AnalysisContext | None = None) -> list[Topic]:
        return ExtractionPipeline().extract(signal, context or AnalysisContext(board_type=signal.board_type)).topics
