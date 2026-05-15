from __future__ import annotations

from typing import Any

from core.framework.workflow import ScopedDataBuffer
from evidence import EvidenceBuilder
from quality import QualityEvent


def build_evidence(buffer: ScopedDataBuffer) -> dict[str, Any]:
    build_result = EvidenceBuilder().build_with_scores(buffer.read("ranked_items"), bundle_id="daily")
    bundle = build_result.bundle
    if not bundle.items:
        raise RuntimeError("no valid evidence built from ranked sources")
    return {
        "evidence_bundle": bundle,
        "evidence_scores": build_result.evidence_scores,
        "candidate_claims": build_result.candidate_claims,
        "verified_findings": build_result.verified_findings,
        "quality_events": [
            quality_event(
                "evidence_build_succeeded",
                evidence_items_count=len(bundle.items),
                evidence_scores_count=len(build_result.evidence_scores),
                candidate_claims_count=len(build_result.candidate_claims),
            ),
            quality_event(
                "claim_verification_succeeded",
                accepted_claims_count=(
                    len(build_result.verified_findings.accepted_claims)
                    if build_result.verified_findings
                    else 0
                ),
                rejected_claims_count=(
                    len(build_result.verified_findings.rejected_claims)
                    if build_result.verified_findings
                    else 0
                ),
                uncertain_claims_count=(
                    len(build_result.verified_findings.uncertain_claims)
                    if build_result.verified_findings
                    else 0
                ),
            ),
        ],
    }


def quality_event(event_type: str, **metadata: Any) -> QualityEvent:
    return QualityEvent(
        event_type=event_type,
        metadata={key: value for key, value in metadata.items() if value is not None},
    )
