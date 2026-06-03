from __future__ import annotations

from typing import Any

from framework.workflow import StepScopedDataBufferView
from business.layers.relation.evidence import EvidenceBuilder
from business.layers.analysis.quality import QualityEvent
from business.boards.cross_board.workflows.daily_intelligence.buffer_key_aliases import (
    with_namespaced_aliases,
)
from business.boards.cross_board.workflows.daily_intelligence.workflow_buffer_access import (
    read_buffer_value,
)
from business.boards.cross_board.workflows.daily_intelligence.source_gate_evidence import (
    SourceGateEvidenceBundleView,
)


def build_evidence(buffer: StepScopedDataBufferView) -> dict[str, Any]:
    build_result = EvidenceBuilder().build_with_scores(
        read_buffer_value(buffer, "ranked_items"),
        bundle_id="daily",
    )
    bundle = build_result.bundle
    if not bundle.items:
        raise RuntimeError("no valid evidence built from ranked sources")
    return with_namespaced_aliases({
        "evidence_bundle": bundle,
        "evidence_scores": build_result.evidence_scores,
        "candidate_claims": build_result.candidate_claims,
        "verified_findings": build_result.verified_findings,
        "quality_events": [
            quality_event(
                "evidence_build_succeeded",
                evidence_items_count=SourceGateEvidenceBundleView.from_bundle(bundle).item_count,
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
    })


def quality_event(event_type: str, **metadata: Any) -> QualityEvent:
    return QualityEvent(
        event_type=event_type,
        metadata={key: value for key, value in metadata.items() if value is not None},
    )
