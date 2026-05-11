from evidence import EvidenceBundle, EvidenceItem
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
    assert result.missing_section_sources == []
    assert result.citation_coverage_score == 1.0


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
