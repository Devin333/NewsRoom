from evidence import EvidenceBundle, EvidenceItem, VerifiedClaim, VerifiedFindings
from quality import CitationChecker, EditorDecision, EditorGate


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


def test_citation_checker_fails_unknown_urls_and_editor_blocks() -> None:
    report = {"sections": [{"title": "Summary", "sources": ["https://example.com/missing"]}]}

    citation_result = CitationChecker().check(report, _bundle())
    review = EditorGate().review(citation_result)

    assert citation_result.passed is False
    assert citation_result.unknown_urls == ["https://example.com/missing"]
    assert citation_result.missing_section_sources == []
    assert citation_result.citation_coverage_score == 1.0
    assert review.decision == EditorDecision.BLOCKED
    assert "https://example.com/missing" in review.reasons


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
