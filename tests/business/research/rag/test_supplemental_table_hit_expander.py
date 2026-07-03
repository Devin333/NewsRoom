from __future__ import annotations

from typing import Any

from business.research.document.models import PaperChunk
from business.research.rag.retrieval.expanders.supplemental_table import SupplementalTableHitExpander
from business.research.rag.retrieval.paper_policy import RetrievalRoute
from business.research.rag.retrieval.paper_retriever import RetrievalPolicy, RetrievalRequest


def _chunk(
    chunk_id: str,
    *,
    chunk_type: str = "paragraph",
    content: str = "Chunk content.",
    paper_id: str = "p1",
    has_table: bool = False,
    metadata: dict[str, Any] | None = None,
) -> PaperChunk:
    return PaperChunk(
        chunk_id=chunk_id,
        paper_id=paper_id,
        parse_source="latex",
        chunk_type=chunk_type,  # type: ignore[arg-type]
        section_title="Results",
        section_role=["analysis"],  # type: ignore[arg-type]
        section_index=1,
        content=content,
        metadata=metadata or {},
        has_table=has_table,
    )


class _Store:
    def __init__(
        self,
        chunks: list[PaperChunk],
        *,
        scores: dict[str, float] | None = None,
        fail: bool = False,
    ) -> None:
        self.chunks = chunks
        self.scores = scores or {}
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    def search_with_scores(
        self,
        paper_id: str,
        query_text: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> list[tuple[PaperChunk, float]]:
        self.calls.append({
            "paper_id": paper_id,
            "query_text": query_text,
            "filters": filters,
            "limit": limit,
        })
        if self.fail:
            raise RuntimeError("store unavailable")
        out: list[tuple[PaperChunk, float]] = []
        for chunk in self.chunks:
            if chunk.paper_id != paper_id:
                continue
            if filters and filters.get("chunk_type") != chunk.chunk_type:
                continue
            out.append((chunk, self.scores.get(chunk.chunk_id, 0.5)))
        return out[:limit]


def test_supplemental_table_expander_injects_scored_table_for_result_query() -> None:
    paragraph = _chunk("para-result", content="Results improve accuracy.")
    table = _chunk(
        "tbl-results",
        chunk_type="table",
        content="Table 1: accuracy improves by 5 points.",
        has_table=True,
    )
    store = _Store([paragraph, table], scores={"tbl-results": 0.8})

    result = SupplementalTableHitExpander(
        store,  # type: ignore[arg-type]
        RetrievalPolicy(supplemental_table_result_limit=2),
    ).expand(
        [paragraph],
        RetrievalRequest(paper_id="p1", question="what do the experiment results show?"),
        RetrievalRoute(intent="numerical_result"),
    )

    assert [chunk.chunk_id for chunk in result] == ["tbl-results"]
    assert store.calls[0]["filters"] == {"chunk_type": "table"}
    assert result[0].metadata["supplemental_reason"] == "result_intent_table_search"
    assert result[0].metadata["fusion_strategy"] == "supplemental_table_text"
    assert result[0].metadata["child_final_score"] > 0.0


def test_supplemental_table_expander_skips_when_table_child_exists() -> None:
    table = _chunk("tbl-existing", chunk_type="table", has_table=True)
    store = _Store([table])

    result = SupplementalTableHitExpander(
        store,  # type: ignore[arg-type]
        RetrievalPolicy(),
    ).expand(
        [table],
        RetrievalRequest(paper_id="p1", question="what do the experiment results show?"),
        RetrievalRoute(intent="numerical_result"),
    )

    assert result == []
    assert store.calls == []


def test_supplemental_table_expander_returns_empty_on_store_failure() -> None:
    store = _Store([], fail=True)

    result = SupplementalTableHitExpander(
        store,  # type: ignore[arg-type]
        RetrievalPolicy(),
    ).expand(
        [_chunk("para-result")],
        RetrievalRequest(paper_id="p1", question="what do the experiment results show?"),
        RetrievalRoute(intent="numerical_result"),
    )

    assert result == []
