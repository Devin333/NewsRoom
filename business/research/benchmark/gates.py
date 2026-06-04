from __future__ import annotations

from business.research.benchmark.models import ResearchSOTAClaim, ResearchScore
from business.research.domain.common import GateResult


def validate_benchmark_score_refs(score: ResearchScore) -> GateResult:
    if not score.source_refs:
        return GateResult.fail("BenchmarkEvidenceLineageGate", "benchmark score requires source refs")
    return GateResult.pass_("BenchmarkEvidenceLineageGate")


def validate_score_range(score: ResearchScore, *, minimum: float = -1_000_000_000, maximum: float = 1_000_000_000) -> GateResult:
    if score.value < minimum or score.value > maximum:
        return GateResult.fail(
            "ScoreRangeGate",
            "benchmark score is outside configured range",
            metadata={"value": score.value, "minimum": minimum, "maximum": maximum},
        )
    return GateResult.pass_("ScoreRangeGate")


def validate_sota_claim_status(claim: ResearchSOTAClaim) -> GateResult:
    if claim.verification_status == "candidate":
        return GateResult.fail("SOTAClaimVerificationGate", "SOTA claim remains candidate-only")
    return GateResult.pass_("SOTAClaimVerificationGate")


__all__ = ["validate_benchmark_score_refs", "validate_score_range", "validate_sota_claim_status"]
