from __future__ import annotations

from typing import Any

from business.research.document.models import PaperChunk
from business.research.rag.retrieval.expanders.formula_context import (
    FormulaContextExpander,
    should_expand_formula_context,
)
from business.research.rag.retrieval.paper_policy import build_retrieval_route
from business.research.rag.retrieval.paper_retriever import RetrievalPolicy, RetrievalRequest


def _chunk(
    chunk_id: str,
    *,
    chunk_type: str = "paragraph",
    parent_chunk_id: str | None = None,
    references: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    has_formula: bool = False,
    formula_latex: str = "",
) -> PaperChunk:
    return PaperChunk(
        chunk_id=chunk_id,
        paper_id="p1",
        parse_source="latex",
        chunk_type=chunk_type,  # type: ignore[arg-type]
        section_title="Method",
        section_role=["method"],  # type: ignore[arg-type]
        section_index=1,
        parent_chunk_id=parent_chunk_id,
        content="Chunk content.",
        references=references or [],
        metadata=metadata or {},
        has_formula=has_formula,
        formula_latex=formula_latex,
    )


def test_formula_context_expands_parent_and_body_refs_for_explanation_query() -> None:
    formula = _chunk(
        "eq-1",
        chunk_type="formula",
        parent_chunk_id="para-parent",
        metadata={"referenced_by_chunks": [{"chunk_id": "para-explain"}]},
        has_formula=True,
        formula_latex="y = Wx",
    )
    policy = RetrievalPolicy(max_formula_context_chunks=4)
    expander = FormulaContextExpander(policy)

    refs = expander.refs_for(
        formula,
        RetrievalRequest(
            paper_id="p1",
            question="How is Equation 1 explained in the surrounding text?",
            limit=1,
        ),
        build_retrieval_route("How is Equation 1 explained in the surrounding text?"),
    )

    assert refs == [
        ("para-explain", "formula_body_reference", "referenced_by_chunks"),
        ("para-parent", "formula_parent_context", "parent_chunk_id"),
    ]


def test_formula_context_expands_reverse_refs_for_formula_query() -> None:
    paragraph = _chunk(
        "para-explain",
        metadata={"formula_chunk_id": "eq-1"},
    )
    expander = FormulaContextExpander(RetrievalPolicy(max_formula_context_chunks=2))

    refs = expander.refs_for(
        paragraph,
        RetrievalRequest(paper_id="p1", question="What is the meaning of Equation 1?", limit=1),
        build_retrieval_route("What is the meaning of Equation 1?"),
    )

    assert refs == [("eq-1", "formula_reverse_reference", "formula_chunk_id")]


def test_formula_context_respects_zero_limit() -> None:
    formula = _chunk(
        "eq-1",
        chunk_type="formula",
        parent_chunk_id="para-parent",
        has_formula=True,
        formula_latex="y = Wx",
    )
    expander = FormulaContextExpander(RetrievalPolicy(max_formula_context_chunks=0))

    refs = expander.refs_for(
        formula,
        RetrievalRequest(paper_id="p1", question="What does Equation 1 mean?", limit=1),
        build_retrieval_route("What does Equation 1 mean?"),
    )

    assert refs == []


def test_formula_context_question_gate() -> None:
    assert should_expand_formula_context("formula_query", "What is the meaning of Equation 1?")
    assert should_expand_formula_context("formula_query", "How is Equation 1 explained?")
    assert not should_expand_formula_context("concept_method", "What does Equation 1 mean?")
