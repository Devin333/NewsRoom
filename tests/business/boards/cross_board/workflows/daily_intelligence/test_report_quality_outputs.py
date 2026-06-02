from __future__ import annotations

from business.boards.cross_board.workflows.daily_intelligence.report_quality_outputs import (
    build_human_review_request,
    build_report_quality_gate_metrics,
    build_report_quality_result,
)


def test_report_quality_outputs_project_route_metrics_and_feedback_metadata() -> None:
    editor_decision = {
        "decision": "rewrite_required",
        "quality_score": 0.42,
        "reasons": ["unsupported claim"],
        "rewrite_instructions": ["remove unsupported claim"],
    }
    metrics = build_report_quality_gate_metrics(
        evidence_bundle={"items": [{"evidence_id": "ev-1"}]},
        verified_findings={
            "accepted_claims": [{"claim_id": "accepted"}],
            "rejected_claims": [{"claim_id": "rejected"}],
            "uncertain_claims": [],
        },
        editor_decision=editor_decision,
        verification_result={
            "unsupported_claims": [{"claim_id": "rejected"}],
            "missing_citations": ["summary"],
            "risk_level": "medium",
        },
        citation_check_result={
            "unknown_urls": ["https://example.com/unknown"],
            "unsupported_evidence_ids": ["ev-missing"],
            "failure_categories": [{"code": "missing_citation"}],
        },
        support_matrix={"unsupported_sections": ["summary"]},
        route="rewrite",
        rewrite_attempts=1,
        human_review_required=False,
    )
    quality_result = build_report_quality_result(
        editor_decision=editor_decision,
        route="rewrite",
        rewrite_attempts=1,
        human_review_required=False,
        quality_gate_metrics=metrics,
        citation_check_result={"failure_categories": [{"code": "missing_citation"}]},
        agent_feedback_metadata={"agent_feedback_event_count": 2},
    )

    assert metrics["rewrite_rate"] == 1.0
    assert metrics["block_rate"] == 0.0
    assert metrics["accepted_claims_count"] == 1
    assert metrics["citation_failure_categories"] == ["missing_citation"]
    assert quality_result["route_history"] == ["rewrite"]
    assert quality_result["metadata"]["agent_feedback_event_count"] == 2
    assert quality_result["metadata"]["remediation"] == ["remove unsupported claim"]


def test_build_human_review_request_uses_fallback_title_and_quality_refs() -> None:
    request = {"run_id": "run-1"}
    editor_decision = {
        "decision": "human_review_required",
        "quality_score": 0.5,
        "reasons": ["needs review"],
        "rewrite_instructions": [],
    }

    review_request = build_human_review_request(
        request=request,
        report_draft={},
        evidence_bundle={"bundle_id": "bundle-1"},
        editor_decision=editor_decision,
        verification_result={"risk_level": "high"},
        fallback_title="Daily Intelligence: fallback",
    )

    assert review_request["run_id"] == "run-1"
    assert review_request["title"] == "Daily Intelligence: fallback"
    assert review_request["reason"] == "quality gate rewrite required"
    assert review_request["quality_artifact_refs"]["quality_result"] == "quality_result.json"
    assert review_request["metadata"]["remediation"] == [
        "human reviewer must approve, reject, or request rewrite"
    ]
