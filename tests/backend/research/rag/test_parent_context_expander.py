from __future__ import annotations

from typing import Any

from backend.research.document.models import PaperChunk
from backend.research.rag.retrieval.expanders.parent import ParentContextExpander
from backend.research.rag.retrieval.paper_policy import build_retrieval_route
from backend.research.rag.retrieval.paper_retriever import RetrievalPolicy, RetrievalRequest


def _chunk(
    chunk_id: str,
    *,
    paper_id: str = "p1",
    parent_chunk_id: str | None = None,
    section_title: str = "Method",
    section_role: list[str] | None = None,
    section_index: int = 1,
    content: str = "The method uses attention.",
    metadata: dict[str, Any] | None = None,
) -> PaperChunk:
    return PaperChunk(
        chunk_id=chunk_id,
        paper_id=paper_id,
        parse_source="latex",
        chunk_type="paragraph",
        section_title=section_title,
        section_role=section_role or ["method"],  # type: ignore[arg-type]
        section_index=section_index,
        parent_chunk_id=parent_chunk_id,
        content=content,
        metadata=metadata or {},
    )


class _Store:
    def __init__(self, chunks: list[PaperChunk]) -> None:
        self.chunks = {chunk.chunk_id: chunk for chunk in chunks}

    def get_chunk(self, chunk_id: str) -> PaperChunk | None:
        return self.chunks.get(chunk_id)


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


def test_parent_expander_falls_back_to_children_when_no_parents() -> None:
    child = _chunk("abstract")
    expander = ParentContextExpander(_Store([child]), RetrievalPolicy())

    parents, metrics = expander.expand(
        [child],
        RetrievalRequest(paper_id="p1", question="what is the method?", limit=1),
        build_retrieval_route("what is the method?"),
    )

    assert parents == [child]
    assert metrics["parent_scoring_enabled"] is False
    assert metrics["parent_candidates_scored"] == 0


def test_parent_expander_returns_child_anchored_snippet_for_long_parent() -> None:
    anchor = "The attention block mixes local and global features for stability."
    parent_content = " ".join(["intro"] * 80 + [anchor] + ["tail"] * 80)
    parent = _chunk("sec-long", content=parent_content)
    child = _chunk("para-anchor", parent_chunk_id="sec-long", content=anchor)
    expander = ParentContextExpander(
        _Store([child, parent]),
        RetrievalPolicy(
            max_parent_tokens=500,
            long_parent_token_threshold=10,
            parent_snippet_token_window=40,
            parent_intent_budgets={},
        ),
    )

    parents, metrics = expander.expand(
        [child],
        RetrievalRequest(paper_id="p1", question="how does attention work?", limit=1),
        build_retrieval_route("how does attention work?"),
    )

    snippet = parents[0]
    assert snippet.chunk_id == "sec-long"
    assert snippet.content != parent_content
    assert anchor in snippet.content
    assert snippet.metadata["parent_snippet"] is True
    assert snippet.metadata["parent_snippet_strategy"] == "child_anchor_window"
    assert snippet.metadata["source_parent_chunk_id"] == "sec-long"
    assert snippet.metadata["parent_anchor_child_id"] == "para-anchor"
    assert metrics["parent_snippets_returned"] == 1


def test_parent_expander_reranker_orders_and_filters_candidates() -> None:
    weak_child = _chunk("weak-child", parent_chunk_id="sec-weak", content="weak child anchor")
    strong_child = _chunk("strong-child", parent_chunk_id="sec-strong", content="strong child anchor")
    weak_parent = _chunk("sec-weak", content="weak-parent gives generic background.")
    strong_parent = _chunk("sec-strong", content="strong-parent explains the exact mechanism.")
    policy = RetrievalPolicy(
        max_parent_chunks=2,
        max_parent_tokens=9999,
        parent_rerank_score_threshold=0.5,
        parent_intent_budgets={},
        reranking_intents=("concept_method",),
    )
    expander = ParentContextExpander(
        _Store([weak_child, strong_child, weak_parent, strong_parent]),
        policy,
        reranker=_KeywordReranker({"strong-parent": 0.95, "weak-parent": 0.2}),
    )

    parents, metrics = expander.expand(
        [weak_child, strong_child],
        RetrievalRequest(paper_id="p1", question="how does the method work?", limit=2),
        build_retrieval_route("how does the method work?"),
    )

    assert [chunk.chunk_id for chunk in parents] == ["sec-strong"]
    parent = parents[0]
    assert parent.metadata["parent_rerank_score"] == 0.95
    assert parent.metadata["parent_rerank_strategy"] == "cross_encoder"
    assert "Matched child evidence:" in parent.metadata["parent_rerank_query"]
    assert parent.metadata["parent_score_strategy"] == "cross_encoder"
    assert metrics["parent_candidates_scored"] == 1


def test_parent_expander_preserves_source_locator_from_child() -> None:
    parent = _chunk("sec-method", content="Method parent.")
    child = _chunk(
        "para-method",
        parent_chunk_id="sec-method",
        metadata={"source_ref": "paper://p1/pdf#page=2"},
    )
    expander = ParentContextExpander(
        _Store([child, parent]),
        RetrievalPolicy(parent_intent_budgets={}),
    )

    parents, _metrics = expander.expand(
        [child],
        RetrievalRequest(paper_id="p1", question="how does the method work?", limit=1),
        build_retrieval_route("how does the method work?"),
    )

    assert parents[0].metadata["source_locator"] == "paper://p1/pdf#page=2"
    assert parents[0].metadata["source_locator_inherited"] is True
    assert parents[0].metadata["source_locator_origin_chunk_id"] == "para-method"
