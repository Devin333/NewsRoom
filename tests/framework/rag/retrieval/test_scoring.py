from __future__ import annotations

from framework.rag.core import RAGEvidence, RAGScoreBreakdown
from framework.rag.retrieval import RAGScoringWeights, fuse_score, score_evidence


def _evidence(chunk_id: str, score: float = 0.0, breakdown: RAGScoreBreakdown | None = None) -> RAGEvidence:
    return RAGEvidence(
        evidence_id=chunk_id,
        chunk_id=chunk_id,
        document_id="doc-1",
        text=f"Evidence {chunk_id}",
        score=score,
        score_breakdown=breakdown or RAGScoreBreakdown(),
    )


def test_fuse_score_uses_present_components_and_normalizes_weights():
    breakdown = RAGScoreBreakdown(
        child_similarity=0.8,
        parent_relevance=0.4,
        field_score=0.2,
    )
    weights = RAGScoringWeights(
        child_similarity=0.5,
        parent_relevance=0.25,
        field_score=0.25,
        section_heading_score=0,
        position_bonus=0,
        rerank_score=0,
    )

    assert fuse_score(breakdown, weights=weights) == 0.55


def test_score_evidence_records_final_score_and_weights_without_fabricating_components():
    evidence = _evidence(
        "chunk-1",
        score=0.1,
        breakdown=RAGScoreBreakdown(child_similarity=0.8),
    )

    scored = score_evidence(evidence)

    assert scored.score == 0.8
    assert scored.score_breakdown.to_dict() == {
        "child_similarity": 0.8,
        "final_score": 0.8,
    }
    assert scored.metadata["rag_score_weights"]["child_similarity"] == 0.5
    assert "parent_relevance" not in evidence.score_breakdown.to_dict()
