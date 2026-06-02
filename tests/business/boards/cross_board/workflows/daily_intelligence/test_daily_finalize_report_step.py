from __future__ import annotations

from dataclasses import dataclass

from framework.workflow import DataBuffer
from business.layers.relation.evidence.models import EvidenceBundle, EvidenceItem, VerifiedClaim, VerifiedFindings
from business.layers.analysis.quality import EditorDecision
from business.boards.cross_board.workflows.daily_intelligence.finalize_report_step import finalize_report
from business.boards.cross_board.workflows.daily_intelligence.report_finalization import (
    DailyReportFinalizationInput,
    finalize_daily_report,
)
from business.boards.cross_board.workflows.daily_intelligence.quality_gate_policy import (
    NON_SOCIAL_MEDIA_BYPASS_REASON,
)


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


def test_report_finalization_usecase_runs_without_workflow_buffer() -> None:
    output = finalize_daily_report(
        DailyReportFinalizationInput(
            request={"topic": "AI policy", "run_id": "run-1"},
            report_draft=_report_draft(),
            editor_review=_editor_review("pass"),
            verification_result={"status": "pass", "risk_level": "low"},
            citation_check_result={"passed": True},
            support_matrix={"coverage_ratio": 1.0},
            evidence_bundle=_evidence_bundle(),
            verified_findings=_verified_findings(),
            quality_events=[],
        )
    )

    assert output["quality_result"]["route"] == "final"
    assert output["final_report"].title == "Daily Intelligence: AI policy"
    assert output["report.final"] == output["final_report"]


def test_finalize_report_projects_agent_feedback_metadata() -> None:
    output = finalize_report(
        _buffer(
            editor_review=_editor_review("pass"),
            agent_feedback_events=[
                {
                    "feedback_id": "feedback-1",
                    "requested_action": "rewrite",
                }
            ],
            agent_feedback_summary={
                "event_count": 1,
                "rewrite_request_count": 1,
                "highest_severity": "warning",
            },
        )
    )

    assert output["final_report"].metadata["agent_feedback_event_count"] == 1
    assert output["final_report"].metadata["agent_feedback_summary"]["rewrite_request_count"] == 1
    assert output["quality_result"]["metadata"]["agent_feedback_summary"]["highest_severity"] == "warning"
    assert output["quality.result"] == output["quality_result"]
    assert output["report.final"] == output["final_report"]


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
            social_evidence=True,
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
            social_evidence=True,
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


def test_finalize_report_invalid_report_draft_blocks_without_system_error() -> None:
    output = finalize_report(
        _buffer(
            report_draft={"title": "Broken", "sections": "not-a-list"},
            editor_review=_editor_review("pass"),
            social_evidence=True,
        )
    )

    assert output["quality_result"]["passed"] is False
    assert output["quality_result"]["route"] == "blocked"
    assert output["quality_gate_metrics"]["blocked"] is True
    assert output["blocked_report"].metadata["quality_route"] == "blocked"
    assert output["blocked_report"].draft["metadata"]["invalid_report_draft"] is True
    assert any("invalid report draft format" in reason for reason in output["blocked_report"].reasons)
    assert output["quality_events"][0].event_type == "finalize_report_invalid_report_draft"
    assert "final_report" not in output


def test_finalize_report_rewrite_required_with_invalid_edited_draft_blocks() -> None:
    output = finalize_report(
        _buffer(
            editor_review=_editor_review(
                "rewrite_required",
                reasons=["tighten unsupported wording"],
                rewrite_instructions=["remove unsupported wording"],
            ),
            edited_report_draft={"title": "Broken edit", "sections": "not-a-list"},
            social_evidence=True,
        )
    )

    assert output["quality_result"]["passed"] is False
    assert output["quality_result"]["route"] == "blocked"
    assert output["quality_gate_metrics"]["rewrite_required"] is True
    assert any("edited report draft is invalid" in reason for reason in output["blocked_report"].reasons)
    assert any(
        event.event_type == "finalize_report_invalid_edited_report_draft"
        for event in output["quality_events"]
    )
    assert "final_report" not in output


def test_finalize_report_rewrite_required_without_edit_blocks() -> None:
    output = finalize_report(
        _buffer(
            editor_review=_editor_review(
                "rewrite_required",
                reasons=["unsupported claim remains"],
                rewrite_instructions=["remove unsupported claim"],
            ),
            social_evidence=True,
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
            ),
            social_evidence=True,
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
            ),
            social_evidence=True,
        )
    )

    assert output["quality_result"]["passed"] is False
    assert output["quality_result"]["decision"] == "blocked"
    assert output["quality_result"]["route"] == "blocked"
    assert output["quality_gate_metrics"]["blocked"] is True
    assert output["blocked_report"].reasons == ["source boundary violated"]
    assert output["blocked_report"].metadata["quality_score"] == 0.2


def test_finalize_report_non_social_media_bypasses_blocking_decision() -> None:
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

    assert output["quality_result"]["passed"] is True
    assert output["quality_result"]["decision"] == "pass"
    assert output["quality_result"]["route"] == "final"
    assert output["quality_result"]["reasons"] == [NON_SOCIAL_MEDIA_BYPASS_REASON]
    assert output["final_report"].title == "Daily Intelligence: AI policy"
    assert output["quality_events"][0].event_type == "finalize_report_bypassed_non_social_media"
    assert "blocked_report" not in output


def test_finalize_report_non_social_bypass_does_not_parse_unused_edited_draft() -> None:
    output = finalize_report(
        _buffer(
            editor_review=_editor_review(
                "rewrite_required",
                reasons=["tighten unsupported wording"],
                rewrite_instructions=["remove unsupported wording"],
            ),
            edited_report_draft={"title": "Unused broken edit", "sections": "not-a-list"},
        )
    )

    assert output["quality_result"]["passed"] is True
    assert output["quality_result"]["route"] == "final"
    assert output["quality_events"][0].event_type == "finalize_report_bypassed_non_social_media"
    assert "blocked_report" not in output


@dataclass(frozen=True)
class _EditorReviewObject:
    decision: EditorDecision
    quality_score: float
    reasons: list[str]
    rewrite_instructions: list[str]


def _buffer(
    *,
    editor_review: dict | _EditorReviewObject,
    report_draft: dict | None = None,
    edited_report_draft: dict | None = None,
    agent_feedback_events: list[dict] | None = None,
    agent_feedback_summary: dict | None = None,
    social_evidence: bool = False,
) -> DataBuffer:
    values = {
        "request": {"topic": "AI policy", "run_id": "run-1"},
        "report_draft": report_draft or _report_draft(),
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
        "evidence_bundle": _evidence_bundle(social=social_evidence),
        "verified_findings": _verified_findings(),
        "quality_events": [],
    }
    if edited_report_draft is not None:
        values["edited_report_draft"] = edited_report_draft
    if agent_feedback_events is not None:
        values["agent_feedback_events"] = agent_feedback_events
    if agent_feedback_summary is not None:
        values["agent_feedback_summary"] = agent_feedback_summary
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
            "agent_feedback_events",
            "agent_feedback_summary",
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


def _evidence_bundle(*, social: bool = False) -> EvidenceBundle:
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
                metadata={"source_type": "reddit"} if social else {"source_type": "rss"},
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
