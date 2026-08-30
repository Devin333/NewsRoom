from __future__ import annotations

from backend.foundation import RelationType
from backend.layers.extraction.models import ExtractionResult
from backend.layers.relation.candidate_rules import claim_predicate_candidates, technology_candidates


class ProposeLinker:
    def link(self, signals, extraction_results: list[ExtractionResult]):
        by_signal = {result.signal_id: result for result in extraction_results}
        candidates = []
        for signal in signals:
            if signal.signal_type.value != "paper":
                continue
            extraction = by_signal.get(signal.signal_id)
            if extraction is None:
                continue
            candidates.extend(technology_candidates(signal, extraction, RelationType.PROPOSES, "ProposeLinker"))
            candidates.extend(claim_predicate_candidates(signal, extraction, "proposes", RelationType.PROPOSES, "ProposeLinker"))
        return candidates
