from __future__ import annotations

from typing import Any

import pytest

from backend.research.document.models import PaperChunk
from backend.research.rag.retrieval.paper_policy import RetrievalRoute
from backend.research.rag.retrieval.paper_retriever import RetrievalPolicy, RetrievalRequest
from backend.research.rag.retrieval.scoring import ChildCandidateScorer


def _chunk(
    chunk_id: str,
    *,
    content: str = "The method improves accuracy.",
    chunk_type: str = "paragraph",
    section_title: str = "Results",
    section_role: list[str] | None = None,
    section_index: int = 1,
    metadata: dict[str, Any] | None = None,
    has_formula: bool = False,
    formula_latex: str = "",
    figure_id: str | None = None,
) -> PaperChunk:
    payload: dict[str, Any] = {
        "chunk_id": chunk_id,
        "paper_id": "p1",
        "parse_source": "latex",
        "chunk_type": chunk_type,
        "section_title": section_title,
        "section_role": section_role or ["analysis"],
        "section_index": section_index,
        "content": content,
        "metadata": metadata or {},
        "has_formula": has_formula,
        "formula_latex": formula_latex,
    }
    if figure_id is not None:
        payload["figure_id"] = figure_id
    return PaperChunk(**payload)


def test_child_candidate_scorer_preserves_field_and_final_score_metadata() -> None:
    chunk = _chunk(
        "fig-1",
        chunk_type="figure",
        content="Caption: attention map highlights syntax.",
        metadata={
            "caption_text": "attention map highlights syntax",
            "field_embedding_scores": {"caption": 0.8, "body": 0.2},
        },
        figure_id="fig-1",
    )
    scored, score = ChildCandidateScorer(RetrievalPolicy()).score(
        chunk,
        RetrievalRequest(paper_id="p1", question="attention map syntax", current_section_index=1),
        RetrievalRoute(intent="figure_query", recall_routes=("figure_chunks",)),
        semantic_score=0.6,
        field_rerank_score=0.7,
    )

    assert score == pytest.approx(scored.metadata["child_final_score"])
    assert scored.metadata["child_score_strategy"] == "semantic_field_embedding_rerank_fusion"
    assert scored.metadata["best_embedding_field"] == "caption"
    assert scored.metadata["best_matching_field"] == "caption"
    assert scored.metadata["field_embedding_score"] == pytest.approx(0.8)
    assert scored.metadata["field_rerank_score"] == pytest.approx(0.7)
    assert scored.metadata["matched_recall_routes"] == ["figure_chunks"]
    assert "caption" in scored.metadata["field_text_available_fields"]


def test_child_candidate_scorer_applies_citation_claim_boost() -> None:
    chunk = _chunk(
        "claim-1",
        content="The proposed model improves accuracy on the benchmark.",
        metadata={"claim_index_score": 0.5},
    )
    scored, _score = ChildCandidateScorer(
        RetrievalPolicy(citation_claim_boost=0.4)
    ).score(
        chunk,
        RetrievalRequest(
            paper_id="p1",
            question="Which paragraph supports the claim: model improves accuracy on benchmark?",
        ),
        RetrievalRoute(intent="citation_query", recall_routes=("abstract_body",)),
        semantic_score=0.2,
    )

    assert scored.metadata["citation_claim_score"] > 0.0
    assert scored.metadata["citation_claim_boost"] > 0.0
    assert scored.metadata["graph_score"] >= 0.5
    assert scored.metadata["child_score_components"]["claim_index"] == pytest.approx(0.5)


def test_child_candidate_scorer_applies_formula_sparse_and_label_boost() -> None:
    chunk = _chunk(
        "eq-1",
        chunk_type="formula",
        content="Equation 3: y = W x",
        metadata={"equation_number": "3"},
        has_formula=True,
        formula_latex="y = W x",
    )
    scored, _score = ChildCandidateScorer(
        RetrievalPolicy(formula_sparse_enabled=True, formula_sparse_boost=0.25)
    ).score(
        chunk,
        RetrievalRequest(paper_id="p1", question="What does Equation 3 y = Wx mean?"),
        RetrievalRoute(intent="formula_query", recall_routes=("formula_chunks",)),
        semantic_score=0.1,
    )

    assert scored.metadata["formula_sparse_hit"] is True
    assert scored.metadata["formula_sparse_boost"] > 0.0
    assert scored.metadata["element_label_match"] is True
    assert scored.metadata["matched_recall_routes"] == ["formula_chunks"]
