from evidence import EvidenceBundle, EvidenceItem, VerifiedClaim, VerifiedFindings
from quality import (
    BlockedReport,
    CitationChecker,
    EditorDecision,
    EditorGate,
    HumanReviewDecision,
    HumanReviewRequest,
    QualityResult,
    QualityScorer,
    SupportMatrixBuilder,
    golden_quality_eval_cases,
    run_quality_eval_case,
)


def _bundle() -> EvidenceBundle:
    return EvidenceBundle(
        bundle_id="bundle",
        items=[
            EvidenceItem(
                evidence_id="ev_1",
                source_url="https://example.com/a",
                title="A",
                summary="A summary covers the main update.",
                confidence=0.9,
                source_id="source",
            )
        ],
    )


def test_support_matrix_marks_supported_sections() -> None:
    report = {
        "sections": [
            {
                "section_id": "summary",
                "title": "Summary",
                "content": "A summary covers the main update.",
                "sources": ["https://example.com/a"],
            }
        ]
    }

    matrix = SupportMatrixBuilder().build(report, _bundle())

    assert matrix.coverage_ratio == 1.0
    assert matrix.sections[0].matched_evidence_ids == ["ev_1"]
    assert matrix.section_claim_evidence_map["summary"]
    assert matrix.sections[0].supported is True


def test_support_matrix_lists_unsupported_claims() -> None:
    report = {
        "sections": [
            {
                "section_id": "summary",
                "title": "Summary",
                "content": "Unsupported robotics acquisition.",
                "sources": ["https://example.com/a"],
            }
        ]
    }

    matrix = SupportMatrixBuilder().build(report, _bundle())

    assert matrix.coverage_ratio == 0.0
    assert matrix.unsupported_claims[0].section_id == "summary"
    assert matrix.unsupported_claims[0].text == "Unsupported robotics acquisition."


def test_support_matrix_prioritizes_explicit_claim_grounding() -> None:
    report = {
        "sections": [
            {
                "section_id": "summary",
                "title": "Summary",
                "content": "A summary covers the main update.",
                "sources": ["https://example.com/a"],
                "claim_grounding": [
                    {
                        "claim_id": "claim_grounded",
                        "text": "A summary covers the main update.",
                        "evidence_ids": ["ev_1"],
                        "source_urls": ["https://example.com/a"],
                    }
                ],
            }
        ]
    }

    matrix = SupportMatrixBuilder().build(report, _bundle())

    assert matrix.section_claim_evidence_map == {"summary": {"claim_grounded": ["ev_1"]}}
    assert matrix.unsupported_claims == []


def test_support_matrix_lists_rejected_claim_usage() -> None:
    findings = VerifiedFindings(
        rejected_claims=[
            VerifiedClaim(
                claim_id="claim_rejected",
                claim="The vendor acquired a rival.",
                status="rejected",
                confidence=1.0,
                rejection_reason="outside bundle",
            )
        ]
    )
    report = {
        "sections": [
            {
                "section_id": "summary",
                "title": "Summary",
                "content": "The vendor acquired a rival.",
                "sources": ["https://example.com/a"],
            }
        ]
    }

    matrix = SupportMatrixBuilder().build(report, _bundle(), findings)

    assert matrix.rejected_claim_usage[0].claim_id == "claim_rejected"
    assert matrix.rejected_claim_usage[0].section_id == "summary"


def test_support_matrix_does_not_auto_support_low_information_claims() -> None:
    report = {
        "sections": [
            {
                "section_id": "summary",
                "title": "Summary",
                "content": "Robotics expansion.",
                "sources": ["https://example.com/a"],
            }
        ]
    }

    matrix = SupportMatrixBuilder().build(report, _bundle())

    assert matrix.coverage_ratio == 0.0
    assert matrix.unsupported_claims[0].text == "Robotics expansion."


def test_quality_scorer_penalizes_unsupported_and_duplicate_sections() -> None:
    report = {
        "sections": [
            {"title": "A", "content": "Same content", "sources": ["https://example.com/a"]},
            {"title": "B", "content": "Same content", "sources": []},
        ]
    }
    citation = CitationChecker().check(report, _bundle())
    matrix = SupportMatrixBuilder().build(report, _bundle())

    summary = QualityScorer().score(
        report=report,
        citation_check=citation,
        support_matrix=matrix,
    )

    assert summary.support_coverage == 0.0
    assert summary.duplicate_sections == ["B"]
    assert summary.quality_score == 0.0
    assert summary.overall_score == 0.0
    assert summary.decision == "blocked"


def test_quality_scorer_degrades_uncertain_unsupported_claims_but_keeps_them_blocked() -> None:
    report = {
        "sections": [
            {
                "title": "Risk / Uncertainty / Verification Notes",
                "content": "Uncertain: the vendor may expand into robotics.",
                "sources": ["https://example.com/a"],
            }
        ]
    }
    citation = CitationChecker().check(report, _bundle())
    matrix = SupportMatrixBuilder().build(report, _bundle())

    summary = QualityScorer().score(
        report=report,
        citation_check=citation,
        support_matrix=matrix,
    )

    assert summary.uncertainty_handling_score > 0.4
    assert summary.claim_support_score == 0.0
    assert summary.decision == "blocked"


def test_editor_gate_requests_rewrite_for_duplicate_supported_sections() -> None:
    report = {
        "sections": [
            {"title": "A", "content": "A summary.", "sources": ["https://example.com/a"]},
            {"title": "B", "content": "A summary.", "sources": ["https://example.com/a"]},
        ]
    }
    citation = CitationChecker().check(report, _bundle())
    matrix = SupportMatrixBuilder().build(report, _bundle())
    summary = QualityScorer().score(
        report=report,
        citation_check=citation,
        support_matrix=matrix,
    )

    review = EditorGate().review(citation, matrix, summary)

    assert citation.passed is True
    assert review.decision == EditorDecision.REWRITE_REQUIRED
    assert "deduplicate repeated report sections" in review.rewrite_instructions


def test_editor_gate_human_review_for_high_risk_borderline_report() -> None:
    report = {
        "title": "Security breach update",
        "sections": [
            {
                "title": "Summary",
                "content": "A summary.",
                "sources": ["https://example.com/a"],
            }
        ],
    }
    citation = CitationChecker().check(report, _bundle())
    matrix = SupportMatrixBuilder().build(report, _bundle())
    summary = QualityScorer().score(
        report=report,
        citation_check=citation,
        support_matrix=matrix,
    )

    review = EditorGate().review(citation, matrix, summary, report_draft=report)

    assert review.decision == EditorDecision.HUMAN_REVIEW
    assert review.required_changes == ["human reviewer must approve, reject, or request rewrite"]


def test_blocked_report_payload_is_standardized() -> None:
    blocked = BlockedReport(
        title="Blocked report",
        blocked_reason="unsupported claims",
        unsupported_claims=[{"claim_id": "claim_1", "text": "Unsupported"}],
        quality_score=0.2,
        next_actions=["remove unsupported claims"],
    )

    payload = blocked.to_dict()

    assert payload["status"] == "blocked"
    assert payload["blocked_reason"] == "unsupported claims"
    assert payload["unsupported_claims"][0]["claim_id"] == "claim_1"
    assert payload["next_actions"] == ["remove unsupported claims"]


def test_human_review_request_payload_and_decision_mapping() -> None:
    request = HumanReviewRequest(
        review_id="review-1",
        run_id="run-1",
        report_id="report-1",
        reason="quality gate blocked",
        risk_level="high",
        review_reason="quality review only",
        claims_to_review=[{"claim_id": "claim_1"}],
        evidence_refs=["ev_1"],
        suggested_decision="request_rewrite",
    )
    base_result = QualityResult(
        decision="human_review",
        passed=False,
        route="human_review",
        blocked=False,
        human_review_required=True,
    )

    mapped = HumanReviewDecision(
        review_id=request.review_id,
        decision="request_rewrite",
    ).to_quality_result(base_result=base_result)

    assert request.to_dict()["review_reason"] == "quality review only"
    assert request.to_dict()["claims_to_review"] == [{"claim_id": "claim_1"}]
    assert mapped.decision == "rewrite_required"
    assert mapped.route == "rewrite"
    assert mapped.rewrite_required is True


def test_quality_eval_golden_cases_pass() -> None:
    records = [run_quality_eval_case(case) for case in golden_quality_eval_cases()]

    assert [record.passed for record in records] == [True, True, True, True, True, True]
    assert [record.expected_decision for record in records] == [
        "pass",
        "pass",
        "rewrite_required",
        "blocked",
        "blocked",
        "blocked",
    ]
    assert [record.actual_decision for record in records] == [
        "pass",
        "pass",
        "rewrite_required",
        "blocked",
        "blocked",
        "blocked",
    ]
    assert records[0].to_dict()["expected_decision"] == "pass"
    assert records[0].to_dict()["actual_decision"] == "pass"
