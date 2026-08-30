from __future__ import annotations

from backend.research.domain.common import CandidateStatus
from backend.research.taxonomy.gates import validate_taxonomy_candidate
from backend.research.taxonomy.models import TaxonomyAssignment, TaxonomyCandidate
from backend.research.taxonomy.registry import TaxonomyRegistry


class TaxonomyAssignmentBuilder:
    def __init__(self, registry: TaxonomyRegistry | None = None) -> None:
        self._registry = registry or TaxonomyRegistry.default()

    def build(self, paper_id: str, candidates: list[TaxonomyCandidate]) -> TaxonomyAssignment:
        domains: list[str] = []
        areas: list[str] = []
        tasks: list[str] = []
        accepted: list[str] = []
        review: list[str] = []
        for candidate in candidates:
            result = validate_taxonomy_candidate(candidate, self._registry)
            if result.passed:
                accepted.append(candidate.candidate_id)
                if candidate.level == "domain":
                    domains.append(candidate.term_id)
                elif candidate.level == "area":
                    areas.append(candidate.term_id)
                elif candidate.level == "task":
                    tasks.append(candidate.term_id)
            else:
                review.append(candidate.candidate_id)
        return TaxonomyAssignment(
            paper_id=paper_id,
            domains=domains,
            areas=areas,
            tasks=tasks,
            accepted_candidate_ids=accepted,
            review_candidate_ids=review,
            metadata={"candidate_status": CandidateStatus.ACCEPTED.value if accepted else CandidateStatus.NEEDS_REVIEW.value},
        )


__all__ = ["TaxonomyAssignmentBuilder"]
