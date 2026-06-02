from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from business.layers.analysis.quality import EditorDecision, EditorReview
from business.boards.cross_board.workflows.daily_intelligence.source_gate_policy import (
    contains_social_media_evidence,
)


NON_SOCIAL_MEDIA_BYPASS_REASON = "non-social media source bypassed strict quality gate"
NON_SOCIAL_MEDIA_BYPASS_FINAL_NOTES = "strict quality gate skipped for non-social media evidence"


@dataclass(frozen=True)
class NonSocialMediaBypassAssessment:
    strict_gate_required: bool
    should_bypass: bool
    event_metadata: dict[str, Any]


def strict_quality_gate_required(evidence_bundle: Any) -> bool:
    return contains_social_media_evidence(evidence_bundle)


def assess_non_social_media_bypass(
    evidence_bundle: Any,
    decision: Any | None = None,
) -> NonSocialMediaBypassAssessment:
    strict_required = strict_quality_gate_required(evidence_bundle)
    decision_value = _decision_value(decision) if decision is not None else None
    should_bypass = not strict_required and (
        decision_value is None or decision_value != EditorDecision.PASS.value
    )
    return NonSocialMediaBypassAssessment(
        strict_gate_required=strict_required,
        should_bypass=should_bypass,
        event_metadata={
            "strict_gate_required": strict_required,
            "bypass_reason": NON_SOCIAL_MEDIA_BYPASS_REASON if should_bypass else None,
            "evidence_items_count": _evidence_items_count(evidence_bundle),
        },
    )


def should_bypass_strict_quality_gate(
    evidence_bundle: Any,
    decision: Any | None = None,
) -> bool:
    return assess_non_social_media_bypass(evidence_bundle, decision).should_bypass


def build_non_social_media_pass_review(
    *,
    citation_check: Any,
    quality_summary: Any,
) -> EditorReview:
    return EditorReview(
        decision=EditorDecision.PASS,
        reasons=[NON_SOCIAL_MEDIA_BYPASS_REASON],
        quality_score=quality_summary.quality_score,
        citation_score=citation_check.citation_coverage_score,
        evidence_alignment_score=quality_summary.evidence_alignment_score,
        readability_score=quality_summary.readability_score,
        duplication_score=quality_summary.duplication_score,
        unsupported_claims=list(citation_check.unsupported_claims),
        hallucination_risks=[
            *citation_check.unknown_urls,
            *citation_check.unsupported_urls,
            *citation_check.unsupported_evidence_ids,
            *citation_check.unsupported_claims,
        ],
        missing_sections=list(citation_check.missing_section_sources),
        final_notes=NON_SOCIAL_MEDIA_BYPASS_FINAL_NOTES,
    )


def build_non_social_media_pass_decision(editor_decision: dict[str, Any]) -> dict[str, Any]:
    next_decision = dict(editor_decision)
    next_decision["decision"] = EditorDecision.PASS.value
    next_decision["reasons"] = [NON_SOCIAL_MEDIA_BYPASS_REASON]
    next_decision["rewrite_instructions"] = []
    return next_decision


def _decision_value(decision: Any) -> str:
    if hasattr(decision, "value"):
        decision = decision.value
    return str(decision or "").strip().lower()


def _evidence_items_count(evidence_bundle: Any) -> int:
    return len(getattr(evidence_bundle, "items", []) or [])


__all__ = [
    "NON_SOCIAL_MEDIA_BYPASS_FINAL_NOTES",
    "NON_SOCIAL_MEDIA_BYPASS_REASON",
    "NonSocialMediaBypassAssessment",
    "assess_non_social_media_bypass",
    "build_non_social_media_pass_decision",
    "build_non_social_media_pass_review",
    "should_bypass_strict_quality_gate",
    "strict_quality_gate_required",
]
