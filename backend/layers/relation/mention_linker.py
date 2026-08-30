from __future__ import annotations

from backend.layers.extraction.models import ExtractionResult
from backend.layers.relation.candidate_rules import mention_candidates


class MentionLinker:
    def link(self, signals, extraction_results: list[ExtractionResult]):
        by_signal = {result.signal_id: result for result in extraction_results}
        candidates = []
        for signal in signals:
            extraction = by_signal.get(signal.signal_id)
            if extraction is not None:
                candidates.extend(mention_candidates(signal, extraction))
        return candidates
