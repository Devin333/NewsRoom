from __future__ import annotations

from typing import Any

from backend.research.document.models import PaperChunk
from backend.research.rag.retrieval.expanders.table_context import TableContextExpander
from backend.research.rag.retrieval.paper_policy import build_retrieval_route
from backend.research.rag.retrieval.paper_retriever import RetrievalPolicy, RetrievalRequest


def _chunk(
    chunk_id: str,
    *,
    paper_id: str = "p1",
    chunk_type: str = "paragraph",
    section_title: str = "Method",
    section_role: list[str] | None = None,
    section_index: int = 1,
    content: str = "Chunk content.",
    parent_chunk_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> PaperChunk:
    return PaperChunk(
        chunk_id=chunk_id,
        paper_id=paper_id,
        parse_source="latex",
        chunk_type=chunk_type,  # type: ignore[arg-type]
        section_title=section_title,
        section_role=section_role or ["method"],  # type: ignore[arg-type]
        section_index=section_index,
        parent_chunk_id=parent_chunk_id,
        content=content,
        metadata=metadata or {},
    )


class _Store:
    def __init__(self, chunks: list[PaperChunk], search_order: list[str] | None = None) -> None:
        self.chunks = {chunk.chunk_id: chunk for chunk in chunks}
        self.search_order = search_order or [chunk.chunk_id for chunk in chunks]

    def get_chunk(self, chunk_id: str) -> PaperChunk | None:
        return self.chunks.get(chunk_id)

    def search_with_scores(
        self,
        paper_id: str,
        query_text: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> list[tuple[PaperChunk, float]]:
        out: list[tuple[PaperChunk, float]] = []
        for index, chunk_id in enumerate(self.search_order):
            chunk = self.chunks[chunk_id]
            if chunk.paper_id != paper_id:
                continue
            if filters and any(getattr(chunk, key, chunk.metadata.get(key)) != value for key, value in filters.items()):
                continue
            out.append((chunk, 1.0 - (index / 100)))
            if len(out) >= limit:
                break
        return out


class _KeywordReranker:
    def __init__(self, scores: dict[str, float]) -> None:
        self.scores = scores
        self.calls: list[tuple[str, list[str]]] = []

    def score(self, query: str, passages: list[str]) -> list[float]:
        self.calls.append((query, passages))
        out: list[float] = []
        for passage in passages:
            out.append(max(
                (score for keyword, score in self.scores.items() if keyword in passage),
                default=0.5,
            ))
        return out


def test_table_context_expands_nearby_and_body_refs_with_locator() -> None:
    table = _chunk(
        "tbl-1",
        chunk_type="table",
        metadata={
            "table_id": "tbl-1",
            "nearby_context_chunk_id": "near-table",
            "referenced_by_chunks": [{"chunk_id": "result-ref"}, {"chunk_id": "missing-ref"}],
            "source_locator": "paper://p1/pdf#page=6",
        },
    )
    nearby = _chunk("near-table")
    referenced = _chunk("result-ref", section_title="Results", section_role=["analysis"])
    foreign = _chunk("foreign-ref", paper_id="p2", section_title="Results", section_role=["analysis"])
    expander = TableContextExpander(
        _Store([table, nearby, referenced, foreign], search_order=["tbl-1", "near-table", "result-ref"]),
        RetrievalPolicy(),
    )

    refs = expander.expand(
        [table],
        RetrievalRequest(paper_id="p1", question="What does Table 1 show?", limit=1),
        build_retrieval_route("What does Table 1 show?"),
    )
    by_id = {chunk.chunk_id: chunk for chunk in refs}

    assert by_id["near-table"].metadata["expansion_reason"] == "table_nearby_context"
    assert by_id["near-table"].metadata["expansion_edge"] == "nearby_context_chunk_id"
    assert by_id["near-table"].metadata["source_locator"] == "paper://p1/pdf#page=6"
    assert by_id["near-table"].metadata["source_locator_inherited"] is True
    assert by_id["result-ref"].metadata["expansion_reason"] == "table_body_reference"
    assert "missing-ref" not in by_id
    assert "foreign-ref" not in by_id


def test_table_context_expands_parent_table_chunk() -> None:
    parent_table = _chunk(
        "tbl-parent",
        chunk_type="table",
        metadata={"table_id": "tbl-2"},
    )
    row_group = _chunk(
        "tbl-row-20",
        chunk_type="table",
        metadata={
            "table_id": "tbl-2",
            "is_table_row_group": True,
            "parent_table_chunk_id": "tbl-parent",
        },
    )
    expander = TableContextExpander(_Store([row_group, parent_table]), RetrievalPolicy())

    refs = expander.expand(
        [row_group],
        RetrievalRequest(paper_id="p1", question="table rare-row-token", limit=1),
        build_retrieval_route("table rare-row-token"),
    )

    assert [chunk.chunk_id for chunk in refs] == ["tbl-parent"]
    assert refs[0].metadata["expansion_reason"] == "table_row_group_parent"
    assert refs[0].metadata["expansion_edge"] == "parent_table_chunk_id"


def test_table_context_skips_generic_experiment_paragraphs() -> None:
    table = _chunk(
        "tbl-results",
        chunk_type="table",
        section_title="Sample Quality",
        section_role=["experiment"],
        section_index=4,
        content="[Table 4]\nSample quality scores.",
        metadata={"table_id": "tbl-results"},
    )
    generic = _chunk(
        "generic-experiment",
        section_title="Reverse Process",
        section_role=["experiment"],
        section_index=4,
        content="Algorithm details describe the sampling loop without interpreting the table.",
    )
    conclusion = _chunk(
        "result-conclusion",
        section_title="Conclusion",
        section_role=["conclusion"],
        section_index=5,
        content="Conclusion: the results show better sample quality and FID scores.",
    )
    expander = TableContextExpander(
        _Store([table, generic, conclusion], search_order=["tbl-results", "generic-experiment", "result-conclusion"]),
        RetrievalPolicy(),
    )

    refs = expander.expand(
        [table],
        RetrievalRequest(paper_id="p1", question="What does Table 4 show?", limit=1),
        build_retrieval_route("What does Table 4 show?"),
    )
    ref_ids = {chunk.chunk_id for chunk in refs}

    assert "result-conclusion" in ref_ids
    assert "generic-experiment" not in ref_ids


def test_table_context_reranker_orders_heuristic_candidates() -> None:
    table = _chunk(
        "tbl-results",
        chunk_type="table",
        section_title="Sample Quality",
        section_role=["experiment"],
        section_index=4,
        content="[Table 4]\nSample quality FID scores.",
        metadata={"table_id": "tbl-results"},
    )
    weak = _chunk(
        "weak-result",
        section_title="Results",
        section_role=["analysis"],
        section_index=4,
        content="Results mention the table but do not explain the key improvement.",
    )
    strong = _chunk(
        "strong-result",
        section_title="Results",
        section_role=["analysis"],
        section_index=4,
        content="Results show the strong-result model improves FID and sample quality.",
    )
    reranker = _KeywordReranker({"strong-result": 0.95, "weak-result": 0.2})
    expander = TableContextExpander(
        _Store([table, weak, strong], search_order=["tbl-results", "weak-result", "strong-result"]),
        RetrievalPolicy(),
        reranker=reranker,
    )

    refs = expander.expand(
        [table],
        RetrievalRequest(paper_id="p1", question="What does Table 4 show?", limit=1),
        build_retrieval_route("What does Table 4 show?"),
    )
    heuristic_refs = [
        chunk for chunk in refs
        if chunk.metadata.get("expansion_reason") == "table_result_context"
    ]

    assert [chunk.chunk_id for chunk in heuristic_refs] == ["strong-result", "weak-result"]
    assert heuristic_refs[0].metadata["table_context_rerank_score"] == 0.95
    assert heuristic_refs[0].metadata["table_context_rerank_strategy"] == "cross_encoder"
    assert "Table evidence:" in heuristic_refs[0].metadata["table_context_rerank_query"]
