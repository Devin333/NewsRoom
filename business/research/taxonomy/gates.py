from __future__ import annotations

from business.foundation import normalize_key
from business.research.domain.common import CandidateStatus, GateResult
from business.research.taxonomy.models import TaxonomyCandidate
from business.research.taxonomy.registry import TaxonomyRegistry


def validate_taxonomy_candidate(candidate: TaxonomyCandidate, registry: TaxonomyRegistry) -> GateResult:
    normalized_term_id = normalize_key(candidate.term_id)
    if not registry.has_term(candidate.level, normalized_term_id):
        return GateResult.fail(
            "TaxonomyRegistryGate",
            "taxonomy candidate is outside the registry",
            metadata={"term_id": normalized_term_id, "level": candidate.level},
        )
    if not candidate.evidence_refs:
        return GateResult.fail("TaxonomyEvidenceGate", "taxonomy candidate requires evidence refs")
    if candidate.status not in {CandidateStatus.CANDIDATE, CandidateStatus.ACCEPTED}:
        return GateResult.fail("TaxonomyStatusGate", "taxonomy candidate must not be pre-rejected by worker")
    return GateResult.pass_("TaxonomyRegistryGate", metadata={"term_id": normalized_term_id, "level": candidate.level})


__all__ = ["validate_taxonomy_candidate"]
