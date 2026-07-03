from __future__ import annotations

from typing import Any

from business.research.document.models import PaperChunk
from business.research.rag.retrieval.expanders.cross_ref import CrossRefContextExpander


def _chunk(
    chunk_id: str,
    *,
    paper_id: str = "p1",
    chunk_type: str = "paragraph",
    content: str = "Chunk content.",
    references: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    has_formula: bool = False,
    formula_latex: str = "",
    has_figure: bool = False,
    figure_id: str = "",
    parent_chunk_id: str | None = None,
) -> PaperChunk:
    return PaperChunk(
        chunk_id=chunk_id,
        paper_id=paper_id,
        parse_source="latex",
        chunk_type=chunk_type,  # type: ignore[arg-type]
        section_title="Method",
        section_role=["method"],  # type: ignore[arg-type]
        section_index=1,
        parent_chunk_id=parent_chunk_id,
        content=content,
        references=references or [],
        metadata=metadata or {},
        has_formula=has_formula,
        formula_latex=formula_latex,
        has_figure=has_figure,
        figure_id=figure_id,
    )


class _Store:
    def __init__(self, chunks: list[PaperChunk]) -> None:
        self.chunks = {chunk.chunk_id: chunk for chunk in chunks}

    def get_chunk(self, chunk_id: str) -> PaperChunk | None:
        return self.chunks.get(chunk_id)

    def list_chunks(self, paper_id: str) -> list[PaperChunk]:
        return [chunk for chunk in self.chunks.values() if chunk.paper_id == paper_id]


def test_cross_ref_expands_first_level_chunk_reference() -> None:
    child = _chunk("para-method", references=["sec-bg"], metadata={"source_ref": "paper://p1/page=2"})
    ref = _chunk("sec-bg")
    expander = CrossRefContextExpander(_Store([child, ref]))

    refs = expander.expand([child], "p1")

    assert [chunk.chunk_id for chunk in refs] == ["sec-bg"]
    assert refs[0].metadata["expansion_reason"] == "chunk_reference"
    assert refs[0].metadata["expanded_from_chunk_id"] == "para-method"
    assert refs[0].metadata["source_locator"] == "paper://p1/page=2"
    assert refs[0].metadata["source_locator_inherited"] is True


def test_cross_ref_expands_page_visual_related_chunks() -> None:
    page = _chunk(
        "page-2",
        chunk_type="figure",
        metadata={
            "page_visual": True,
            "related_visual_chunks": [{"chunk_id": "fig-1"}],
        },
    )
    figure = _chunk("fig-1", chunk_type="figure")
    expander = CrossRefContextExpander(_Store([page, figure]))

    refs = expander.expand([page], "p1")

    assert [chunk.chunk_id for chunk in refs] == ["fig-1"]
    assert refs[0].metadata["expansion_reason"] == "page_visual_related_chunk"
    assert refs[0].metadata["expansion_edge"] == "page_visual_related_chunk"


def test_cross_ref_expands_figure_body_reference() -> None:
    figure = _chunk(
        "fig-1",
        chunk_type="figure",
        has_figure=True,
        metadata={"referenced_by_chunks": [{"chunk_id": "para-ref"}]},
    )
    paragraph = _chunk("para-ref")
    expander = CrossRefContextExpander(_Store([figure, paragraph]))

    refs = expander.expand([figure], "p1")

    assert [chunk.chunk_id for chunk in refs] == ["para-ref"]
    assert refs[0].metadata["expansion_reason"] == "figure_body_reference"
    assert refs[0].metadata["expansion_edge"] == "referenced_by_chunks"


def test_cross_ref_expands_formula_reverse_context() -> None:
    formula = _chunk(
        "eq-1",
        chunk_type="formula",
        has_formula=True,
        formula_latex="x + y",
    )
    explanation = _chunk(
        "para-explain",
        metadata={"formula_chunk_id": "eq-1"},
    )
    expander = CrossRefContextExpander(_Store([formula, explanation]))

    refs = expander.expand([formula], "p1")

    assert [chunk.chunk_id for chunk in refs] == ["para-explain"]
    assert refs[0].metadata["expansion_reason"] == "formula_reverse_context"
    assert refs[0].metadata["expansion_edge"] == "formula_reverse_context"
