from __future__ import annotations

from business.foundation import RelationType
from business.layers.extraction.models import ExtractionResult
from business.layers.relation.candidate_rules import claim_predicate_candidates, technology_candidates


class DiscussLinker:
    def link(self, signals, extraction_results: list[ExtractionResult]):
        by_signal = {result.signal_id: result for result in extraction_results}
        candidates = []
        for signal in signals:
            if signal.signal_type.value != "community_discussion":
                continue
            extraction = by_signal.get(signal.signal_id)
            if extraction is None:
                continue
            candidates.extend(technology_candidates(signal, extraction, RelationType.DISCUSSES, "DiscussLinker"))
            candidates.extend(claim_predicate_candidates(signal, extraction, "discusses", RelationType.DISCUSSES, "DiscussLinker"))
        return candidates
