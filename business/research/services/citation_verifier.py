from __future__ import annotations

from business.research.domain.common import GateResult
from business.research.domain.evidence import ResearchClaim, ResearchEvidencePack


class CitationVerifier:
    def verify_claims(self, claims: list[ResearchClaim], evidence_pack: ResearchEvidencePack) -> list[GateResult]:
        available = set(evidence_pack.evidence_ids)
        results: list[GateResult] = []
        for claim in claims:
            missing = [evidence_id for evidence_id in claim.evidence_ids if evidence_id not in available]
            if not claim.evidence_ids:
                results.append(GateResult.fail("ClaimEvidenceGate", "claim requires evidence ids", metadata={"claim_id": claim.claim_id}))
            elif missing:
                results.append(
                    GateResult.fail(
                        "ClaimEvidenceGate",
                        "claim references missing evidence ids",
                        metadata={"claim_id": claim.claim_id, "missing": missing},
                    )
                )
            else:
                results.append(GateResult.pass_("ClaimEvidenceGate", metadata={"claim_id": claim.claim_id}))
        return results


__all__ = ["CitationVerifier"]
