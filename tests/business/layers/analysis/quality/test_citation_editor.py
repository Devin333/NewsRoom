from business.foundation.models.source import Lineage
from business.layers.relation.evidence import EvidenceBundle, EvidenceItem, VerifiedClaim, VerifiedFindings
from business.layers.analysis.quality import CitationChecker, EditorDecision, EditorGate, EditorReview, RewritePolicy


def _bundle() -> EvidenceBundle:
    return EvidenceBundle(
        bundle_id="bundle",
        items=[
            EvidenceItem(
                evidence_id="ev_1",
                source_url="https://example.com/a",
                title="A",
                summary="A summary",
                confidence=0.9,
                source_id="source",
                source_item_id="source-item-1",
                lineage=Lineage(source_id="source", source_item_id="source-item-1"),
            )
        ],
    )


def test_citation_checker_passes_known_urls() -> None:
    report = {"sections": [{"title": "Summary", "sources": ["https://example.com/a"]}]}

    result = CitationChecker().check(report, _bundle())

    assert result.passed is True
    assert result.unknown_urls == []
    assert result.unsupported_urls == []
    assert result.missing_section_sources == []
    assert result.citation_coverage_score == 1.0
    assert result.claim_support_score == 1.0


def test_citation_checker_matches_historical_source_url_aliases() -> None:
    bundle = EvidenceBundle(
        bundle_id="bundle",
        items=[
            EvidenceItem(
                evidence_id="ev_legacy",
                source_url="https://example.com/News/?topic=AI",
                title="Legacy source",
                summary="Legacy source summary",
                confidence=0.9,
                source_id="source",
                source_item_id="source-item-legacy",
                lineage=Lineage(source_id="source", source_item_id="source-item-legacy"),
            )
        ],
    )
    report = {
        "sections": [
            {
                "title": "Summary",
                "sources": ["https://example.com/News?Topic=AI"],
            }
        ]
    }

    result = CitationChecker().check(report, bundle)

    assert result.unknown_urls == []
    assert result.unsupported_urls == []


def test_citation_checker_passes_known_evidence_ids() -> None:
    report = {
        "sections": [
            {
                "title": "Summary",
                "content": "A summary",
                "evidence_ids": ["ev_1"],
            }
        ]
    }

    result = CitationChecker().check(report, _bundle())

    assert result.passed is True
    assert result.cited_evidence_ids == ["ev_1"]


def test_citation_checker_uses_explicit_claim_grounding_to_pass_supported_claim() -> None:
    report = {
        "sections": [
            {
                "section_id": "summary",
                "title": "Summary",
                "content": "A summary",
                "sources": ["https://example.com/a"],
                "claim_grounding": [
                    {
                        "claim_id": "claim_1",
                        "text": "A summary",
                        "evidence_ids": ["ev_1"],
                        "source_urls": ["https://example.com/a"],
                    }
                ],
            }
        ]
    }

    result = CitationChecker().check(report, _bundle())

    assert result.passed is True
    assert result.unsupported_claims == []
    assert result.claim_support_score == 1.0


def test_citation_checker_fails_unknown_urls_and_editor_blocks() -> None:
    report = {"sections": [{"title": "Summary", "sources": ["https://example.com/missing"]}]}

    citation_result = CitationChecker().check(report, _bundle())
    review = EditorGate().review(citation_result)

    assert citation_result.passed is False
    assert citation_result.unknown_urls == ["https://example.com/missing"]
    assert citation_result.unsupported_urls == []
    assert citation_result.missing_section_sources == []
    assert citation_result.citation_coverage_score == 1.0
    assert review.decision == EditorDecision.BLOCKED
    assert "https://example.com/missing" in review.reasons




def test_citation_checker_fails_non_publishable_urls() -> None:
    bundle = EvidenceBundle(
        bundle_id="bundle",
        items=[
            EvidenceItem(
                evidence_id="ev_1",
                source_url="https://example.com/a",
                title="A",
                summary="A summary",
                confidence=0.9,
                source_id="source",
                source_item_id="source-item-1",
                publishable=False,
            )
        ],
    )
    report = {"sections": [{"title": "Summary", "sources": ["https://example.com/a"]}]}

    result = CitationChecker().check(report, bundle)

    assert result.passed is False
    assert result.unknown_urls == []
    assert result.unsupported_urls == ["https://example.com/a"]


def test_citation_checker_fails_missing_section_sources_and_editor_blocks() -> None:
    report = {"sections": [{"title": "No Sources", "content": "Uncited text."}]}

    citation_result = CitationChecker().check(report, _bundle())
    review = EditorGate().review(citation_result)

    assert citation_result.passed is False
    assert citation_result.unknown_urls == []
    assert citation_result.missing_section_sources == ["No Sources"]
    assert citation_result.citation_coverage_score == 0.0
    assert review.decision == EditorDecision.BLOCKED
    assert "report sections missing source citations" in review.reasons
    assert "missing section sources: No Sources" in review.reasons


def test_citation_checker_flags_unsupported_claims() -> None:
    report = {
        "sections": [
            {
                "title": "Summary",
                "content": "This section invents a quantum chip acquisition.",
                "sources": ["https://example.com/a"],
            }
        ]
    }

    result = CitationChecker().check(report, _bundle())

    assert result.passed is False
    assert result.unsupported_claims == [
        "Summary: This section invents a quantum chip acquisition."
    ]
    assert result.claim_support_score == 0.0


def test_citation_checker_flags_claim_that_adds_new_fact_to_cited_evidence() -> None:
    bundle = EvidenceBundle(
        bundle_id="bundle",
        items=[
            EvidenceItem(
                evidence_id="ev_1",
                source_url="https://example.com/a",
                title="The model update improves inference latency",
                summary="The vendor released a model update that improves inference latency.",
                confidence=0.9,
                source_id="source",
            )
        ],
    )
    report = {
        "sections": [
            {
                "title": "Edit",
                "content": "The vendor released a model update and expanded into robotics.",
                "sources": ["https://example.com/a"],
            }
        ]
    }

    result = CitationChecker().check(report, bundle)

    assert result.passed is False
    assert result.unsupported_claims == [
        "Edit: The vendor released a model update and expanded into robotics."
    ]


def test_citation_checker_blocks_weak_overlap_without_explicit_grounding() -> None:
    report = {
        "sections": [
            {
                "title": "Summary",
                "content": "Policy update mentions unrelated robotics expansion.",
                "sources": ["https://example.com/a"],
            }
        ]
    }

    result = CitationChecker().check(report, _bundle())

    assert result.passed is False
    assert result.unsupported_claims == [
        "Summary: Policy update mentions unrelated robotics expansion."
    ]


def test_citation_checker_flags_rejected_claim_usage() -> None:
    findings = VerifiedFindings(
        rejected_claims=[
            VerifiedClaim(
                claim_id="claim_rejected",
                claim="The vendor acquired a rival.",
                status="rejected",
                confidence=1.0,
                rejecting_sources=["https://example.com/outside"],
            )
        ]
    )
    report = {
        "sections": [
            {
                "title": "Summary",
                "content": "The vendor acquired a rival.",
                "sources": ["https://example.com/a"],
            }
        ]
    }

    result = CitationChecker().check(report, _bundle(), findings)
    review = EditorGate().review(result)

    assert result.passed is False
    assert result.rejected_claim_usage == ["The vendor acquired a rival."]
    assert review.decision == EditorDecision.BLOCKED
    assert "report uses rejected claims as facts" in review.reasons


def test_citation_checker_exposes_failure_categories_and_section_results() -> None:
    findings = VerifiedFindings(
        rejected_claims=[
            VerifiedClaim(
                claim_id="claim_rejected",
                claim="The vendor acquired a rival.",
                status="rejected",
                confidence=1.0,
            )
        ]
    )
    report = {
        "sections": [
            {
                "section_id": "summary",
                "title": "Summary",
                "content": "The vendor acquired a rival.",
                "sources": ["https://example.com/missing"],
                "evidence_ids": ["ev_missing"],
            },
            {
                "section_id": "notes",
                "title": "Notes",
                "content": "Uncited note.",
            },
        ]
    }

    result = CitationChecker().check(report, _bundle(), findings)
    payload = result.to_dict()

    assert result.passed is False
    assert payload["failure_category_codes"] == [
        "unknown_urls",
        "unsupported_evidence_ids",
        "missing_section_sources",
        "unsupported_claims",
        "rejected_claim_usage",
        "failing_sections",
    ]
    assert payload["failure_categories"][0] == {
        "code": "unknown_urls",
        "count": 1,
        "items": ["https://example.com/missing"],
    }
    section_results = {section["section_id"]: section for section in payload["section_results"]}
    assert section_results["summary"]["passed"] is False
    assert section_results["summary"]["issue_codes"] == [
        "unknown_urls",
        "unsupported_evidence_ids",
        "unsupported_claims",
        "rejected_claim_usage",
    ]
    assert section_results["notes"]["issue_codes"] == ["missing_section_sources", "unsupported_claims"]


def test_rewrite_policy_blocks_rewrite_that_adds_new_source_url() -> None:
    rewritten = {
        "sections": [
            {
                "title": "Summary",
                "content": "A summary",
                "sources": ["https://example.com/new"],
            }
        ]
    }

    result = RewritePolicy().validate_rewrite(
        rewritten_report=rewritten,
        evidence_bundle=_bundle(),
    )

    assert result.passed is False
    assert result.new_source_urls == ["https://example.com/new"]
    assert result.decision == EditorDecision.BLOCKED


def test_rewrite_policy_instructions_list_claim_deletion_and_citation_fixes() -> None:
    instructions = RewritePolicy().instructions_for(
        EditorReview(
            decision=EditorDecision.REWRITE_REQUIRED,
            unsupported_claims=["Summary: Unsupported robotics acquisition."],
            missing_sections=["Summary"],
        )
    )

    assert instructions == [
        "delete or downgrade unsupported claim: Summary: Unsupported robotics acquisition.",
        "add citation from existing evidence only: Summary",
    ]


def test_rewrite_policy_accepts_rewrite_after_unsupported_claim_removed() -> None:
    rewritten = {
        "sections": [
            {
                "title": "Summary",
                "content": "A summary",
                "sources": ["https://example.com/a"],
            }
        ]
    }

    result = RewritePolicy().validate_rewrite(
        rewritten_report=rewritten,
        evidence_bundle=_bundle(),
    )

    assert result.passed is True
    assert result.unsupported_claims == []
    assert result.decision == EditorDecision.PASS


def test_rewrite_policy_blocks_rewrite_that_still_has_unsupported_claims() -> None:
    rewritten = {
        "sections": [
            {
                "title": "Summary",
                "content": "This section still invents a quantum chip acquisition.",
                "sources": ["https://example.com/a"],
            }
        ]
    }

    result = RewritePolicy().validate_rewrite(
        rewritten_report=rewritten,
        evidence_bundle=_bundle(),
    )

    assert result.passed is False
    assert result.unsupported_claims == [
        "Summary: This section still invents a quantum chip acquisition."
    ]
    assert result.decision == EditorDecision.BLOCKED


def test_rewrite_policy_does_not_allow_uncertain_claim_as_fact() -> None:
    findings = VerifiedFindings(
        uncertain_claims=[
            VerifiedClaim(
                claim_id="claim_uncertain",
                claim="A deployment date is set.",
                status="uncertain",
                confidence=0.4,
                uncertainty_reason="no evidence",
            )
        ]
    )
    rewritten = {
        "sections": [
            {
                "title": "Summary",
                "content": "A deployment date is set.",
                "sources": ["https://example.com/a"],
            }
        ]
    }

    result = RewritePolicy().validate_rewrite(
        rewritten_report=rewritten,
        evidence_bundle=_bundle(),
        verified_findings=findings,
    )

    assert result.passed is False
    assert result.uncertain_claims_as_fact == ["A deployment date is set."]
