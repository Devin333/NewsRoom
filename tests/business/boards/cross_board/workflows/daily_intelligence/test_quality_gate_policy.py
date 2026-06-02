from __future__ import annotations

from business.boards.cross_board.workflows.daily_intelligence.quality_gate_policy import (
    NON_SOCIAL_MEDIA_BYPASS_REASON,
    build_non_social_media_pass_decision,
    should_bypass_strict_quality_gate,
    strict_quality_gate_required,
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

    bypass_decision = build_non_social_media_pass_decision(editor_decision)

    assert bypass_decision["decision"] == "pass"
    assert bypass_decision["reasons"] == [NON_SOCIAL_MEDIA_BYPASS_REASON]
    assert bypass_decision["rewrite_instructions"] == []


def test_social_evidence_requires_strict_quality_gate() -> None:
    evidence_bundle = _evidence_bundle(source_type="reddit")

    assert strict_quality_gate_required(evidence_bundle) is True
    assert should_bypass_strict_quality_gate(evidence_bundle, "blocked") is False


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
