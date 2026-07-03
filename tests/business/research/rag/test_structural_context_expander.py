from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from business.research.document.models import PaperChunk
from business.research.rag.retrieval.expanders.structural import StructuralContextExpander
from business.research.rag.retrieval.paper_policy import RetrievalRoute
from business.research.rag.retrieval.paper_retriever import RetrievalPolicy, RetrievalRequest


def _chunk(
    chunk_id: str,
    *,
    chunk_type: str = "paragraph",
    content: str | None = None,
    paper_id: str = "p1",
    parent_chunk_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    has_table: bool = False,
    has_figure: bool = False,
    has_formula: bool = False,
    figure_id: str | None = None,
    formula_latex: str = "",
) -> PaperChunk:
    payload: dict[str, Any] = {
        "paper_id": paper_id,
        "chunk_id": chunk_id,
        "parent_chunk_id": parent_chunk_id,
        "parse_source": "latex",
        "chunk_type": chunk_type,
        "section_title": "Results",
        "section_index": 1,
        "content": content or chunk_id,
        "metadata": metadata or {},
        "has_table": has_table,
        "has_figure": has_figure,
        "has_formula": has_formula,
        "formula_latex": formula_latex,
    }
    if figure_id is not None:
        payload["figure_id"] = figure_id
    return PaperChunk(**payload)


@dataclass
class _ChunkStore:
    chunks: list[PaperChunk]

    def get_chunk(self, chunk_id: str) -> PaperChunk | None:
        return {chunk.chunk_id: chunk for chunk in self.chunks}.get(chunk_id)


def test_figure_query_interleaves_nearby_context_with_source_locator() -> None:
    figure = _chunk(
        "fig-1",
        chunk_type="figure",
        has_figure=True,
        figure_id="fig-1",
        metadata={
            "nearby_context_chunk_id": "para-near",
            "source_locator": "paper://p1/pdf#page=3&pdf_rect=1,2,3,4",
        },
    )
    nearby = _chunk("para-near", metadata={"graph_score": 0.2})

    result = StructuralContextExpander(
        _ChunkStore([figure, nearby]),
        RetrievalPolicy(max_figure_context_chunks=1),
    ).expand(
        [figure],
        RetrievalRequest(paper_id="p1", question="what does the figure show?"),
        RetrievalRoute(intent="figure_query"),
    )

    assert [chunk.chunk_id for chunk in result] == ["fig-1", "para-near"]
    expanded = result[1]
    assert expanded.metadata["expansion_reason"] == "figure_nearby_context"
    assert expanded.metadata["expansion_edge"] == "nearby_context_chunk_id"
    assert expanded.metadata["expansion_rank"] == 1
    assert expanded.metadata["graph_score"] == 1.0
    assert expanded.metadata["source_locator"] == "paper://p1/pdf#page=3&pdf_rect=1,2,3,4"
    assert expanded.metadata["source_locator_inherited"] is True
    assert expanded.metadata["source_locator_origin_chunk_id"] == "fig-1"


def test_table_query_interleaves_body_reference_and_parent_context() -> None:
    table = _chunk(
        "tbl-1",
        chunk_type="table",
        has_table=True,
        parent_chunk_id="sec-results",
        metadata={
            "referenced_by_chunks": [{"chunk_id": "para-ref"}],
            "parent_table_chunk_id": "tbl-parent",
        },
    )
    body_ref = _chunk("para-ref")
    parent_table = _chunk("tbl-parent", chunk_type="table", has_table=True)
    section_parent = _chunk("sec-results")

    result = StructuralContextExpander(
        _ChunkStore([table, body_ref, parent_table, section_parent]),
        RetrievalPolicy(max_table_context_chunks=3),
    ).expand(
        [table],
        RetrievalRequest(paper_id="p1", question="what do the results show?"),
        RetrievalRoute(intent="table_query"),
    )

    assert [chunk.chunk_id for chunk in result] == ["tbl-1", "para-ref", "tbl-parent", "sec-results"]
    by_id = {chunk.chunk_id: chunk for chunk in result}
    assert by_id["para-ref"].metadata["expansion_reason"] == "table_body_reference"
    assert by_id["tbl-parent"].metadata["expansion_reason"] == "table_row_group_parent"
    assert by_id["sec-results"].metadata["expansion_reason"] == "table_parent_context"


def test_formula_query_interleaves_parent_context() -> None:
    formula = _chunk(
        "eq-1",
        chunk_type="formula",
        has_formula=True,
        formula_latex="a^2 + b^2 = c^2",
        parent_chunk_id="para-parent",
    )
    parent = _chunk("para-parent", content="The formula explains the distance relation.")

    result = StructuralContextExpander(
        _ChunkStore([formula, parent]),
        RetrievalPolicy(max_formula_context_chunks=1),
    ).expand(
        [formula],
        RetrievalRequest(paper_id="p1", question="explain what the formula means"),
        RetrievalRoute(intent="formula_query"),
    )

    assert [chunk.chunk_id for chunk in result] == ["eq-1", "para-parent"]
    assert result[1].metadata["expansion_reason"] == "formula_parent_context"
    assert result[1].metadata["expansion_edge"] == "parent_chunk_id"


def test_structural_expander_dedupes_and_skips_cross_paper_refs() -> None:
    figure = _chunk(
        "fig-1",
        chunk_type="figure",
        has_figure=True,
        metadata={"nearby_context_chunk_id": "para-near"},
    )
    nearby = _chunk("para-near")
    other_paper = _chunk("other-paper", paper_id="p2")
    second_figure = _chunk(
        "fig-2",
        chunk_type="figure",
        has_figure=True,
        metadata={"nearby_context_chunk_id": "other-paper"},
    )

    result = StructuralContextExpander(
        _ChunkStore([figure, nearby, other_paper, second_figure]),
        RetrievalPolicy(max_figure_context_chunks=2),
    ).expand(
        [figure, nearby, second_figure],
        RetrievalRequest(paper_id="p1", question="show the figure"),
        RetrievalRoute(intent="figure_query"),
    )

    assert [chunk.chunk_id for chunk in result] == ["fig-1", "para-near", "fig-2"]
