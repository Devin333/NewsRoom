from evidence import EvidenceBundle, EvidenceItem
from quality import CitationChecker, EditorDecision, EditorGate, QualityScorer, SupportMatrixBuilder


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


def test_support_matrix_marks_supported_sections() -> None:
    report = {"sections": [{"title": "Summary", "sources": ["https://example.com/a"]}]}

    matrix = SupportMatrixBuilder().build(report, _bundle())

    assert matrix.coverage_ratio == 1.0
    assert matrix.sections[0].matched_evidence_ids == ["ev_1"]
    assert matrix.sections[0].supported is True


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

    assert summary.support_coverage == 0.5
    assert summary.duplicate_sections == ["B"]
    assert summary.quality_score == 0.6


def test_editor_gate_blocks_unsupported_sections_even_when_citations_pass() -> None:
    report = {"sections": [{"title": "Unsupported", "content": "No sources", "sources": []}]}
    citation = CitationChecker().check(report, _bundle())
    matrix = SupportMatrixBuilder().build(report, _bundle())
    summary = QualityScorer().score(
        report=report,
        citation_check=citation,
        support_matrix=matrix,
    )

    review = EditorGate().review(citation, matrix, summary)

    assert citation.passed is True
    assert review.decision == EditorDecision.BLOCKED
    assert review.quality_score == 0.6
    assert "unsupported section: Unsupported" in review.reasons
