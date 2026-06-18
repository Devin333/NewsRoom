from __future__ import annotations

from hashlib import sha256
from typing import Any

from business.layers.relation.evidence import EvidenceBundle, EvidenceItem, VerifiedClaim, VerifiedFindings
from business.layers.relation.evidence import Lineage
from business.layers.analysis.quality.citation_checker import CitationChecker
from business.layers.analysis.quality.editor_gate import EditorGate
from business.layers.analysis.quality.models import QualityEvalCase, QualityEvalRecord
from business.layers.analysis.quality.scoring import QualityScorer
from business.layers.analysis.quality.support_matrix import SupportMatrixBuilder


def golden_quality_eval_cases() -> list[QualityEvalCase]:
    return [
        _case(
            "grounded-pass",
            "pass",
            "AI policy update: Policy summary.",
            ["https://example.com/ai-policy"],
            section_evidence_ids=["ev_policy"],
            claim_grounding=[
                {
                    "claim_id": "claim_grounded_pass",
                    "text": "AI policy update: Policy summary.",
                    "evidence_ids": ["ev_policy"],
                    "source_urls": ["https://example.com/ai-policy"],
                }
            ],
        ),
        _case(
            "pass",
            "pass",
            "AI policy update: Policy summary.",
            ["https://example.com/ai-policy"],
        ),
        _case(
            "rewrite",
            "rewrite_required",
            "AI policy update: Policy summary.",
            ["https://example.com/ai-policy"],
            duplicate=True,
        ),
        _case(
            "block",
            "blocked",
            "This report invents a critical safety breach.",
            ["https://example.com/ai-policy"],
        ),
        _case(
            "rejected",
            "blocked",
            "The vendor acquired a rival.",
            ["https://example.com/ai-policy"],
            rejected_claim="The vendor acquired a rival.",
        ),
        _case(
            "live-malformed-support",
            "blocked",
            "OpenAI has partnered with the Government of Malta to provide ChatGPT Plus subscriptions and AI skills training to all Maltese citizens.",
            ["https://openai.com/index/malta-chatgpt-plus-partnership"],
            evidence_title="OpenAI partners with Malta",
            evidence_summary="OpenAI announced a Malta partnership focused on ChatGPT Plus access and AI literacy.",
        ),
    ]


def run_quality_eval_case(case: QualityEvalCase) -> QualityEvalRecord:
    verified_findings = case.request.get("verified_findings")
    citation_check = CitationChecker().check(
        case.report_draft,
        case.evidence_bundle,
        verified_findings,
    )
    support_matrix = SupportMatrixBuilder().build(
        case.report_draft,
        case.evidence_bundle,
        verified_findings,
    )
    quality_summary = QualityScorer().score(
        report=case.report_draft,
        citation_check=citation_check,
        support_matrix=support_matrix,
    )
    editor_review = EditorGate().review(
        citation_check,
        support_matrix,
        quality_summary,
        report_draft=case.report_draft,
    )
    expected = case.expected_decision
    actual = editor_review.decision.value
    differences = [] if expected == actual else [f"expected {expected}, got {actual}"]
    return QualityEvalRecord(
        eval_id=f"eval_{sha256(case.case_id.encode('utf-8')).hexdigest()[:12]}",
        case_id=case.case_id,
        citation_check_result=citation_check,
        editor_review=editor_review,
        quality_summary=quality_summary,
        passed=not differences,
        expected_decision=expected,
        actual_decision=actual,
        differences=differences,
    )


def _case(
    case_id: str,
    expected_decision: str,
    content: str,
    sources: list[str],
    *,
    duplicate: bool = False,
    rejected_claim: str | None = None,
    uncertain_claim: str | None = None,
    evidence_title: str = "AI policy update",
    evidence_summary: str = "Policy summary.",
    section_evidence_ids: list[str] | None = None,
    claim_grounding: list[dict[str, Any]] | None = None,
) -> QualityEvalCase:
    bundle = _bundle(title=evidence_title, summary=evidence_summary)
    sections: list[dict[str, Any]] = [
        {
            "section_id": "summary",
            "title": "Summary",
            "content": content,
            "sources": sources,
            "evidence_ids": list(section_evidence_ids or []),
            "claim_grounding": list(claim_grounding or []),
        }
    ]
    if duplicate:
        sections.append(dict(sections[0], section_id="summary_copy", title="Summary copy"))
    findings = VerifiedFindings()
    if rejected_claim:
        findings = VerifiedFindings(
            rejected_claims=[
                VerifiedClaim(
                    claim_id="claim_rejected",
                    claim=rejected_claim,
                    status="rejected",
                    confidence=1.0,
                    rejection_reason="golden rejected claim",
                    notes="golden rejected claim",
                )
            ]
        )
    if uncertain_claim:
        findings = VerifiedFindings(
            uncertain_claims=[
                VerifiedClaim(
                    claim_id="claim_uncertain",
                    claim=uncertain_claim,
                    status="uncertain",
                    confidence=0.4,
                    uncertainty_reason="golden uncertain claim",
                    notes="golden uncertain claim",
                )
            ]
        )
    return QualityEvalCase(
        case_id=case_id,
        request={"topic": "AI policy", "verified_findings": findings},
        evidence_bundle=bundle,
        report_draft={
            "title": "Daily Intelligence: AI policy",
            "sections": sections,
        },
        expected_decision=expected_decision,
        expected_unsupported_claims=[],
    )


def _bundle(*, title: str = "AI policy update", summary: str = "Policy summary.") -> EvidenceBundle:
    return EvidenceBundle(
        bundle_id="golden",
        topic="AI policy",
        items=[
            EvidenceItem(
                evidence_id="ev_policy",
                source_url="https://example.com/ai-policy",
                title=title,
                summary=summary,
                confidence=0.9,
                source_id="fixture",
                source_item_id="raw-policy",
                source_item_ids=["raw-policy"],
                source_urls=["https://example.com/ai-policy"],
                source_reliability="high",
                lineage=Lineage(source_id="fixture", source_item_id="raw-policy"),
            )
        ],
    )
