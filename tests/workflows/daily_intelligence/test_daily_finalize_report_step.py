from __future__ import annotations

from dataclasses import dataclass

from framework.workflow import DataBuffer
from evidence.models import EvidenceBundle, EvidenceItem, VerifiedClaim, VerifiedFindings
from quality import EditorDecision
from workflows.daily_intelligence.finalize_report_step import finalize_report


def test_finalize_report_pass_publishes_final_report_and_markdown() -> None:
    output = finalize_report(_buffer(editor_review=_editor_review("pass")))

    assert output["quality_result"]["passed"] is True
    assert output["quality_result"]["route"] == "final"
    assert output["quality_gate_metrics"]["blocked"] is False
    assert output["final_report"].title == "Daily Intelligence: AI policy"
    assert output["final_report"].metadata["accepted_claims_count"] == 1
    assert output["final_report"].sections[0]["claim_grounding"][0]["claim_id"] == "claim-1"
    assert "https://example.com/source" in output["report_markdown"]
    assert "blocked_report" not in output


def test_finalize_report_rewrite_required_with_edited_draft_publishes_edit() -> None:
    edited_draft = _report_draft(title="Edited Daily Intelligence")
    edited_draft["sections"][0]["content"] = "Edited source-grounded summary."
    output = finalize_report(
        _buffer(
            editor_review=_editor_review(
                "rewrite_required",
                reasons=["tighten unsupported wording"],
                rewrite_instructions=["remove unsupported wording"],
            ),
            edited_report_draft=edited_draft,
        )
    )

    assert output["quality_result"]["passed"] is True
    assert output["quality_result"]["decision"] == "rewrite_required"
    assert output["quality_result"]["route"] == "rewrite"
    assert output["quality_result"]["rewrite_attempts"] == 1
    assert output["final_report"].title == "Edited Daily Intelligence"
    assert output["final_report"].sections[0]["claim_grounding"][0]["claim_id"] == "claim-1"
    assert "Edited source-grounded summary." in output["report_markdown"]
    assert output["rewrite_instructions"] == ["remove unsupported wording"]


def test_finalize_report_rewrite_required_with_invalid_source_blocks() -> None:
    edited_draft = _report_draft(title="Edited Daily Intelligence")
    edited_draft["sections"][0]["sources"] = ["https://example.com/outside"]

    output = finalize_report(
        _buffer(
            editor_review=_editor_review(
                "rewrite_required",
                reasons=["tighten unsupported wording"],
                rewrite_instructions=["remove unsupported wording"],
            ),
            edited_report_draft=edited_draft,
        )
    )

    assert output["quality_result"]["passed"] is False
    assert output["quality_result"]["route"] == "blocked"
    assert output["quality_gate_metrics"]["rewrite_required"] is True
    assert "final_report" not in output
    assert any(
        "outside evidence bundle" in reason
        for reason in output["blocked_report"].reasons
    )


def test_finalize_report_rewrite_required_without_edit_blocks() -> None:
    output = finalize_report(
        _buffer(
            editor_review=_editor_review(
                "rewrite_required",
                reasons=["unsupported claim remains"],
                rewrite_instructions=["remove unsupported claim"],
            )
        )
    )

    assert output["quality_result"]["passed"] is False
    assert output["quality_result"]["route"] == "blocked"
    assert output["quality_gate_metrics"]["rewrite_required"] is True
    assert output["blocked_report"].reasons == ["unsupported claim remains"]
    assert output["rewrite_instructions"] == ["remove unsupported claim"]
    assert output["quality_result"]["metadata"]["remediation"] == ["remove unsupported claim"]
    assert "final_report" not in output


def test_finalize_report_human_review_required_creates_request_and_blocked_marker() -> None:
    output = finalize_report(
        _buffer(
            editor_review=_editor_review(
                "human_review",
                reasons=["borderline high-risk topic"],
            )
        )
    )

    assert output["quality_result"]["passed"] is False
    assert output["quality_result"]["route"] == "human_review"
    assert output["quality_result"]["human_review_required"] is True
    assert output["quality_gate_metrics"]["human_review_required"] is True
    assert output["human_review_request"]["status"] == "pending"
    assert output["human_review_request"]["reason"] == "quality gate rewrite required"
    assert output["human_review_request"]["metadata"]["remediation"] == [
        "human reviewer must approve, reject, or request rewrite"
    ]
    assert output["blocked_report"].metadata["human_review_required"] is True
    assert output["quality_result"]["metadata"]["remediation"] == [
        "human reviewer must approve, reject, or request rewrite"
    ]


def test_finalize_report_block_decision_creates_blocked_report() -> None:
    output = finalize_report(
        _buffer(
            editor_review=_EditorReviewObject(
                decision=EditorDecision.BLOCKED,
                quality_score=0.2,
                reasons=["source boundary violated"],
                rewrite_instructions=[],
            )
        )
    )

    assert output["quality_result"]["passed"] is False
    assert output["quality_result"]["decision"] == "blocked"
    assert output["quality_result"]["route"] == "blocked"
    assert output["quality_gate_metrics"]["blocked"] is True
    assert output["blocked_report"].reasons == ["source boundary violated"]
    assert output["blocked_report"].metadata["quality_score"] == 0.2


@dataclass(frozen=True)
class _EditorReviewObject:
    decision: EditorDecision
    quality_score: float
    reasons: list[str]
    rewrite_instructions: list[str]


def _buffer(
    *,
    editor_review: dict | _EditorReviewObject,
    edited_report_draft: dict | None = None,
) -> DataBuffer:
    values = {
        "request": {"topic": "AI policy", "run_id": "run-1"},
        "report_draft": _report_draft(),
        "editor_review": editor_review,
        "verification_result": {
            "status": "pass",
            "unsupported_claims": [],
            "missing_citations": [],
            "risk_level": "low",
            "reasons": [],
            "grounded_claims": [
                {
                    "claim_id": "claim-1",
                    "section_id": "summary",
                    "status": "supported",
                    "evidence_ids": ["ev-1"],
                    "source_urls": ["https://example.com/source"],
                    "reason": "explicit grounding",
                }
            ],
        },
        "citation_check_result": {"passed": True, "unsupported_claims": []},
        "support_matrix": {"coverage_ratio": 1.0, "unsupported_sections": []},
        "evidence_bundle": _evidence_bundle(),
        "verified_findings": _verified_findings(),
        "quality_events": [],
    }
    if edited_report_draft is not None:
        values["edited_report_draft"] = edited_report_draft
    return DataBuffer(values).scope(
        read_keys=[
            "request",
            "report_draft",
            "edited_report_draft",
            "editor_review",
            "verification_result",
            "citation_check_result",
            "support_matrix",
            "evidence_bundle",
            "verified_findings",
            "quality_events",
        ],
        optional_read_keys=["edited_report_draft"],
        write_keys=[],
    )


def _editor_review(
    decision: str,
    *,
    reasons: list[str] | None = None,
    rewrite_instructions: list[str] | None = None,
) -> dict:
    return {
        "decision": decision,
        "quality_score": 0.92,
        "reasons": reasons or ["quality threshold met"],
        "rewrite_instructions": rewrite_instructions or [],
    }


def _report_draft(*, title: str = "Daily Intelligence: AI policy") -> dict:
    return {
        "title": title,
        "sections": [
            {
                "section_id": "summary",
                "title": "Summary",
                "content": "Source-grounded summary.",
                "sources": ["https://example.com/source"],
                "evidence_ids": ["ev-1"],
                "claim_grounding": [
                    {
                        "claim_id": "claim-1",
                        "text": "Source-grounded summary.",
                        "evidence_ids": ["ev-1"],
                        "source_urls": ["https://example.com/source"],
                    }
                ],
            }
        ],
        "metadata": {"draft_id": "draft-1"},
    }


def _evidence_bundle() -> EvidenceBundle:
    return EvidenceBundle(
        bundle_id="bundle-1",
        topic="AI policy",
        items=[
            EvidenceItem(
                evidence_id="ev-1",
                source_url="https://example.com/source",
                title="Evidence source",
                summary="Source-grounded summary.",
                confidence=1.0,
                source_id="source-1",
                source_item_id="item-1",
            )
        ],
    )


def _verified_findings() -> VerifiedFindings:
    return VerifiedFindings(
        accepted_claims=[
            VerifiedClaim(
                claim_id="claim-1",
                claim="Source-grounded summary.",
                status="accepted",
                confidence=1.0,
                supporting_evidence_ids=["ev-1"],
                supporting_sources=["https://example.com/source"],
            )
        ]
    )
