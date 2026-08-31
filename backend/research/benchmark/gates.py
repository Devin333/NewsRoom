from __future__ import annotations

from backend.research.benchmark.models import ResearchSOTAClaim, ResearchScore
from backend.research.domain.common import GateResult


def validate_benchmark_score_refs(score: ResearchScore) -> GateResult:
    if not score.source_refs:
        return GateResult.fail("BenchmarkEvidenceLineageGate", "benchmark score requires source refs")
    if not score.source_snapshot_refs:
        return GateResult.fail(
            "BenchmarkEvidenceLineageGate",
            "benchmark score requires source snapshot refs",
        )
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
    if claim.verification_status != "verified":
        return GateResult.fail(
            "SOTAClaimVerificationGate",
            "SOTA claim is not verified",
            metadata={"status": claim.verification_status},
        )
    missing = [
        name
        for name, value in (
            ("score_id", claim.score_id),
            ("benchmark_id", claim.benchmark_id),
            ("dataset_id", claim.dataset_id),
            ("metric_id", claim.metric_id),
            ("source_snapshot_refs", claim.source_snapshot_refs),
            ("evidence_refs", claim.evidence_refs),
            ("dataset_version", claim.dataset_version),
            ("split", claim.split),
            ("unit", claim.unit),
            ("direction", claim.direction),
            ("evaluation_protocol", claim.evaluation_protocol),
        )
        if value is None or (isinstance(value, (list, tuple, set)) and not value) or not str(value).strip()
    ]
    if missing:
        return GateResult.fail(
            "SOTAClaimEvidenceGate",
            "verified SOTA claim is missing required lineage or protocol fields",
            metadata={"missing": missing},
        )
    return GateResult.pass_("SOTAClaimVerificationGate")


__all__ = ["validate_benchmark_score_refs", "validate_score_range", "validate_sota_claim_status"]
