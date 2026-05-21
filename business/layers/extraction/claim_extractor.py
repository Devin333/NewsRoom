from __future__ import annotations

from business.foundation import AnalysisContext, Claim, Signal
from business.layers.extraction.pipeline import ExtractionPipeline


class ClaimExtractor:
    def extract(self, signal: Signal, context: AnalysisContext | None = None) -> list[Claim]:
        return ExtractionPipeline().extract(signal, context or AnalysisContext(board_type=signal.board_type)).claims
