from __future__ import annotations

from business.layers.extraction.models import ExtractionResult
from business.layers.relation.candidate_rules import compare_candidates


class CompareLinker:
    def link(self, signals, extraction_results: list[ExtractionResult]):
        return compare_candidates(list(signals), extraction_results)
