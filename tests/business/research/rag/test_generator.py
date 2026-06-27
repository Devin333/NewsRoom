from __future__ import annotations

from business.research.document.models import PaperChunk
from business.research.rag.generator import AnswerContextAssembler
from business.research.rag.retriever import RetrievalResult


def test_answer_context_assembler_interleaves_related_context() -> None:
    figure = _chunk(
        "fig-1",
        "figure",
        "[Figure 1] Caption: architecture.",
        metadata={"nearby_context_chunk_id": "para-near"},
    )
    unrelated = _chunk("para-other", "paragraph", "Other paragraph.")
    nearby = _chunk("para-near", "paragraph", "Figure 1 explains the architecture.")
    parent = _chunk("section-parent", "paragraph", "Parent section.")
    retrieval = RetrievalResult(
        parent_chunks=[nearby, parent],
        child_chunks=[figure, unrelated],
        ref_chunks=[],
        intent="figure_query",  # type: ignore[arg-type]
    )

    selection = AnswerContextAssembler(max_context_chunks=3).select(retrieval)

    assert [chunk.chunk_id for chunk in selection.chunks] == ["fig-1", "para-near", "para-other"]
    assert selection.metadata["context_source_buckets"] == {
        "fig-1": "child",
        "para-near": "parent",
        "para-other": "child",
    }
    assert selection.metadata["related_context_ids"] == ["para-near"]


def test_answer_context_assembler_uses_ref_chunks_before_leftover_candidates() -> None:
    table = _chunk(
        "table-1",
        "table",
        "[Table 1] Caption: results.",
        metadata={"referenced_by_chunks": [{"chunk_id": "result-para"}]},
    )
    result_para = _chunk("result-para", "paragraph", "The results improve accuracy.")
    other = _chunk("other", "paragraph", "Other paragraph.")
    retrieval = RetrievalResult(
        parent_chunks=[],
        child_chunks=[table, other],
        ref_chunks=[result_para],
        intent="table_query",  # type: ignore[arg-type]
    )

    selection = AnswerContextAssembler(max_context_chunks=3).select(retrieval)

    assert [chunk.chunk_id for chunk in selection.chunks] == ["table-1", "result-para", "other"]


def _chunk(
    chunk_id: str,
    chunk_type: str,
    content: str,
    *,
    metadata: dict | None = None,
) -> PaperChunk:
    return PaperChunk(
        chunk_id=chunk_id,
        paper_id="p1",
        parse_source="latex",
        chunk_type=chunk_type,  # type: ignore[arg-type]
        content=content,
        metadata=metadata or {},
    )
