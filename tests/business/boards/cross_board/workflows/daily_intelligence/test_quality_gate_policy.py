from __future__ import annotations

from business.boards.cross_board.workflows.daily_intelligence.quality_gate_policy import (
    NON_SOCIAL_MEDIA_BYPASS_REASON,
    assess_non_social_media_bypass,
    build_non_social_media_pass_decision,
    should_bypass_strict_quality_gate,
    strict_quality_gate_required,
)
from business.boards.cross_board.workflows.daily_intelligence.source_gate_evidence import (
    SourceGateEvidenceBundleView,
)
from business.layers.relation.evidence.models import EvidenceBundle, EvidenceItem


def test_non_social_evidence_can_bypass_blocking_quality_decision() -> None:
    evidence_bundle = _evidence_bundle(source_type="rss")
    editor_decision = {
        "decision": "blocked",
        "reasons": ["source boundary violated"],
        "rewrite_instructions": ["remove unsupported source"],
    }

    assert strict_quality_gate_required(evidence_bundle) is False
    assert should_bypass_strict_quality_gate(evidence_bundle, "blocked") is True
    assessment = assess_non_social_media_bypass(evidence_bundle, "blocked")
    assert assessment.should_bypass is True
    assert assessment.strict_gate_required is False
    assert assessment.event_metadata["bypass_reason"] == NON_SOCIAL_MEDIA_BYPASS_REASON
    assert assessment.event_metadata["evidence_items_count"] == 1

    bypass_decision = build_non_social_media_pass_decision(editor_decision)

    assert bypass_decision["decision"] == "pass"
    assert bypass_decision["reasons"] == [NON_SOCIAL_MEDIA_BYPASS_REASON]
    assert bypass_decision["rewrite_instructions"] == []


def test_social_evidence_requires_strict_quality_gate() -> None:
    evidence_bundle = _evidence_bundle(source_type="reddit")

    assert strict_quality_gate_required(evidence_bundle) is True
    assert should_bypass_strict_quality_gate(evidence_bundle, "blocked") is False
    assert assess_non_social_media_bypass(evidence_bundle, "blocked").should_bypass is False


def test_non_social_pass_decision_does_not_emit_bypass() -> None:
    evidence_bundle = _evidence_bundle(source_type="rss")

    assessment = assess_non_social_media_bypass(evidence_bundle, "pass")

    assert assessment.should_bypass is False
    assert assessment.strict_gate_required is False
    assert assessment.event_metadata["bypass_reason"] is None


def test_bypass_assessment_consumes_source_gate_evidence_view() -> None:
    evidence_bundle = SourceGateEvidenceBundleView.from_bundle(_evidence_bundle(source_type="rss"))

    assessment = assess_non_social_media_bypass(evidence_bundle, "blocked")

    assert assessment.should_bypass is True
    assert assessment.event_metadata["evidence_items_count"] == evidence_bundle.item_count


def _evidence_bundle(*, source_type: str) -> EvidenceBundle:
    return EvidenceBundle(
        bundle_id="bundle-1",
        items=[
            EvidenceItem(
                evidence_id="ev-1",
                source_url="https://example.com/source",
                title="Evidence source",
                summary="Source-grounded summary.",
                confidence=1.0,
                source_id="source-1",
                source_item_id="item-1",
                metadata={"source_type": source_type},
            )
        ],
    )
