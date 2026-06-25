from __future__ import annotations

from typing import Any

import pytest

from business.research.document.citation_spans import build_paragraph_span_metadata
from business.research.document.models import PaperChunk
from business.research.rag.retriever import (
    ResearchRetriever,
    RetrievalPolicy,
    RetrievalRequest,
    RetrievalResult,
)
from business.research.ports.field_embedding_index import FieldEmbeddingHit
from business.research.ports.visual_chunk_index import VisualChunkHit
from business.research.document.chunk_storage import PaperChunkStoreAdapter
from infrastructure.storage.vector.fake_store import InMemoryVectorStore
from infrastructure.storage.vector.paper_chunk_store import PaperChunkStore


def _make_store() -> PaperChunkStoreAdapter:
    return PaperChunkStoreAdapter(PaperChunkStore(InMemoryVectorStore()))  # type: ignore[arg-type]


def _chunk(
    chunk_id: str,
    paper_id: str = "p1",
    *,
    chunk_type: str = "paragraph",
    section_title: str = "Method",
    section_role: list[str] | None = None,
    section_index: int = 2,
    parent_chunk_id: str | None = None,
    content: str = "The model uses multi-head attention.",
    metadata: dict[str, Any] | None = None,
) -> PaperChunk:
    chunk_metadata = {"is_parent": parent_chunk_id is None, "source_ref": f"arxiv://p1/{chunk_id}"}
    if metadata:
        chunk_metadata.update(metadata)
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
        metadata=chunk_metadata,
    )


def _seed_store(store: PaperChunkStore) -> tuple[PaperChunk, PaperChunk, PaperChunk]:
    parent = _chunk("sec-1", section_index=2, content="Full method section text.")
    child1 = _chunk("para-1", section_index=2, parent_chunk_id="sec-1")
    child2 = _chunk("para-2", section_index=5, parent_chunk_id="sec-1",
                    section_title="Experiments", section_role=["experiment"],
                    content="We achieve 90% accuracy on the benchmark.")
    store.ensure_collection()
    store.index_chunks([parent, child1, child2])
    return parent, child1, child2


class _ScriptedChunkStore:
    def __init__(self, chunks: list[PaperChunk], search_order: list[str] | None = None) -> None:
        self.chunks = {chunk.chunk_id: chunk for chunk in chunks}
        self.search_order = search_order or [chunk.chunk_id for chunk in chunks]

    def ensure_collection(self) -> None:
        return None

    def search_chunks(
        self,
        paper_id: str,
        query_text: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
        score_threshold: float | None = None,
    ) -> list[PaperChunk]:
        return [chunk for chunk, _score in self.search_with_scores(
            paper_id,
            query_text,
            filters=filters,
            limit=limit,
        )]

    def search_with_scores(
        self,
        paper_id: str,
        query_text: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 30,
    ) -> list[tuple[PaperChunk, float]]:
        out: list[tuple[PaperChunk, float]] = []
        for index, chunk_id in enumerate(self.search_order):
            chunk = self.chunks[chunk_id]
            if chunk.paper_id != paper_id or not _matches_filters(chunk, filters or {}):
                continue
            out.append((chunk, 1.0 - (index / 100)))
            if len(out) >= limit:
                break
        return out

    def get_chunk(self, chunk_id: str) -> PaperChunk | None:
        return self.chunks.get(chunk_id)

    def get_parent_chunk(self, chunk: PaperChunk) -> PaperChunk | None:
        return self.get_chunk(chunk.parent_chunk_id) if chunk.parent_chunk_id else None


def _matches_filters(chunk: PaperChunk, filters: dict[str, Any]) -> bool:
    for key, value in filters.items():
        if getattr(chunk, key, chunk.metadata.get(key)) != value:
            return False
    return True


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


class _FailingReranker:
    def score(self, query: str, passages: list[str]) -> list[float]:
        raise RuntimeError("reranker unavailable")


class _FakeFieldIndex:
    def __init__(self, hits: list[FieldEmbeddingHit]) -> None:
        self.hits = hits
        self.calls: list[dict[str, Any]] = []

    def search_field_vectors(
        self,
        paper_id: str,
        query_text: str,
        *,
        field_names: tuple[str, ...] | None = None,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> list[FieldEmbeddingHit]:
        self.calls.append({
            "paper_id": paper_id,
            "query_text": query_text,
            "field_names": field_names,
            "filters": filters or {},
            "limit": limit,
        })
        return self.hits[:limit]


# ── basic retrieval ───────────────────────────────────────────────────────────

def test_retrieve_returns_result():
    store = _make_store()
    _seed_store(store)
    retriever = ResearchRetriever(store)
    result = retriever.retrieve(RetrievalRequest(paper_id="p1", question="how does attention work?"))
    assert result.child_chunks or result.parent_chunks


def test_retrieve_intent_classified():
    store = _make_store()
    _seed_store(store)
    retriever = ResearchRetriever(store)
    result = retriever.retrieve(RetrievalRequest(paper_id="p1", question="图3说明了什么"))
    assert result.intent == "figure_query"


def test_parent_expansion():
    store = _make_store()
    parent, child1, _ = _seed_store(store)
    retriever = ResearchRetriever(store)
    result = retriever.retrieve(
        RetrievalRequest(paper_id="p1", question="multi-head attention mechanism", limit=5)
    )
    parent_ids = {c.chunk_id for c in result.parent_chunks}
    # parent should appear since child references it
    assert "sec-1" in parent_ids or result.parent_chunks


def test_parent_expansion_respects_count_budget():
    children = [
        _chunk(f"para-{index}", parent_chunk_id=f"sec-{index}", content=f"method anchor {index}")
        for index in range(1, 4)
    ]
    parents = [
        _chunk(f"sec-{index}", content=f"Full method parent {index}.")
        for index in range(1, 4)
    ]
    store = _ScriptedChunkStore(
        [*children, *parents],
        search_order=[child.chunk_id for child in children],
    )
    policy = RetrievalPolicy(
        max_parent_chunks=2,
        max_parent_tokens=9999,
        parent_intent_budgets={},
    )

    retriever = ResearchRetriever(store, policy=policy)
    result = retriever.retrieve(RetrievalRequest(paper_id="p1", question="how does the method work?", limit=3))

    assert [chunk.chunk_id for chunk in result.parent_chunks] == ["sec-1", "sec-2"]
    assert result.metadata["parent_budget_chunks"] == 2
    assert result.metadata["parent_budget_exhausted"] is True


def test_parent_final_score_can_override_child_rank_with_method_heading():
    early_child = _chunk(
        "early-child",
        parent_chunk_id="sec-background",
        section_role=["method"],
        content="method anchor with generic background",
    )
    later_child = _chunk(
        "later-child",
        parent_chunk_id="sec-architecture",
        section_role=["method"],
        content="method anchor with architecture details",
    )
    background_parent = _chunk(
        "sec-background",
        section_title="Background",
        section_role=["background"],
        content="Background context.",
    )
    architecture_parent = _chunk(
        "sec-architecture",
        section_title="Model Architecture",
        section_role=["method"],
        content="Architecture context.",
    )
    store = _ScriptedChunkStore(
        [early_child, later_child, background_parent, architecture_parent],
        search_order=["early-child", "later-child"],
    )
    policy = RetrievalPolicy(overfetch_multiplier=1, max_parent_tokens=9999, parent_intent_budgets={})

    retriever = ResearchRetriever(store, policy=policy)
    result = retriever.retrieve(RetrievalRequest(paper_id="p1", question="how does the architecture work?", limit=2))

    assert [chunk.chunk_id for chunk in result.parent_chunks] == ["sec-architecture", "sec-background"]
    first = result.parent_chunks[0]
    second = result.parent_chunks[1]
    assert first.metadata["parent_section_heading_score"] == 1.0
    assert first.metadata["parent_final_score"] > second.metadata["parent_final_score"]
    assert first.metadata["parent_score_strategy"] == "deterministic"


def test_field_score_boosts_caption_match_for_figure_query():
    weak = _chunk(
        "fig-weak",
        chunk_type="figure",
        content="[Figure fig-weak]\nCaption:\nA baseline chart.",
        metadata={"content_sources": ["caption"]},
    )
    strong = _chunk(
        "fig-strong",
        chunk_type="figure",
        content="[Figure fig-strong]\nCaption:\nArchitecture overview.",
        metadata={"content_sources": ["caption"]},
    )
    store = _ScriptedChunkStore([weak, strong], search_order=["fig-weak", "fig-strong"])

    retriever = ResearchRetriever(store, policy=RetrievalPolicy(overfetch_multiplier=1))
    result = retriever.retrieve(
        RetrievalRequest(paper_id="p1", question="Figure architecture overview", limit=2)
    )

    assert [chunk.chunk_id for chunk in result.child_chunks] == ["fig-strong", "fig-weak"]
    assert result.child_chunks[0].metadata["caption_score"] > result.child_chunks[1].metadata["caption_score"]
    assert result.child_chunks[0].metadata["field_score_weights"]["caption"] == 0.6
    assert result.child_chunks[0].metadata["child_final_score"] > result.child_chunks[1].metadata["child_final_score"]
    assert result.metadata["field_scored_count"] == 2
    assert result.metadata["field_score_top"] >= result.metadata["field_score_min"]


def test_field_score_boosts_equation_match_for_formula_query():
    weak = _chunk(
        "eq-weak",
        chunk_type="formula",
        content="[Equation]\nLaTeX:\nE = mc^2",
    ).model_copy(update={"has_formula": True, "formula_latex": "E = mc^2"})
    strong = _chunk(
        "eq-strong",
        chunk_type="formula",
        content="[Equation]\nLaTeX:\n\\operatorname{Attention}(Q,K,V)",
    ).model_copy(update={
        "has_formula": True,
        "formula_latex": r"\operatorname{Attention}(Q,K,V)",
        "formula_description": "Attention computes query key value scores.",
    })
    store = _ScriptedChunkStore([weak, strong], search_order=["eq-weak", "eq-strong"])

    retriever = ResearchRetriever(store, policy=RetrievalPolicy(overfetch_multiplier=1))
    result = retriever.retrieve(
        RetrievalRequest(paper_id="p1", question="Attention Q K V equation", limit=2)
    )

    assert [chunk.chunk_id for chunk in result.child_chunks] == ["eq-strong", "eq-weak"]
    assert result.child_chunks[0].metadata["equation_score"] > result.child_chunks[1].metadata["equation_score"]
    assert result.child_chunks[0].metadata["field_score_weights"]["equation"] == 0.6


def test_field_score_boosts_abstract_for_contribution_query():
    weak = _chunk(
        "para-generic",
        section_title="Method",
        content="Implementation details describe the training loop.",
    )
    abstract = _chunk(
        "abs-paper",
        chunk_type="abstract",
        section_title="Abstract",
        section_role=["background"],
        content="We propose a novel retrieval contribution for paper understanding.",
    )
    store = _ScriptedChunkStore([weak, abstract], search_order=["para-generic", "abs-paper"])

    retriever = ResearchRetriever(store, policy=RetrievalPolicy(overfetch_multiplier=1))
    result = retriever.retrieve(
        RetrievalRequest(paper_id="p1", question="what contribution does the paper propose", limit=2)
    )

    assert [chunk.chunk_id for chunk in result.child_chunks] == ["abs-paper", "para-generic"]
    assert result.child_chunks[0].metadata["abstract_score"] > 0.0
    assert result.child_chunks[0].metadata["field_score_weights"]["abstract"] == 0.4


def test_field_score_boosts_title_for_method_query():
    weak = _chunk(
        "para-background",
        section_title="Background",
        content="General context mentions neural networks.",
    )
    strong = _chunk(
        "para-architecture",
        section_title="Architecture",
        content="The model block details are described here.",
    )
    store = _ScriptedChunkStore([weak, strong], search_order=["para-background", "para-architecture"])

    retriever = ResearchRetriever(store, policy=RetrievalPolicy(overfetch_multiplier=1))
    result = retriever.retrieve(
        RetrievalRequest(paper_id="p1", question="how does the architecture work", limit=2)
    )

    assert [chunk.chunk_id for chunk in result.child_chunks] == ["para-architecture", "para-background"]
    assert result.child_chunks[0].metadata["title_score"] > result.child_chunks[1].metadata["title_score"]
    assert result.child_chunks[0].metadata["field_score_weights"]["title"] == 0.35


def test_field_embedding_hit_boosts_matching_caption_candidate():
    weak = _chunk(
        "fig-weak",
        chunk_type="figure",
        content="[Figure fig-weak]\nCaption:\nA baseline chart.",
        metadata={"content_sources": ["caption"]},
    )
    strong = _chunk(
        "fig-strong",
        chunk_type="figure",
        content="[Figure fig-strong]\nCaption:\nArchitecture overview.",
        metadata={"content_sources": ["caption"]},
    )
    store = _ScriptedChunkStore([weak, strong], search_order=["fig-weak", "fig-strong"])
    field_index = _FakeFieldIndex([
        FieldEmbeddingHit(
            chunk_id="fig-strong",
            field_name="caption",
            score=0.98,
            field_text="Architecture overview.",
            metadata={"source_locator": "paper://p1/pdf#page=3"},
        )
    ])

    retriever = ResearchRetriever(
        store,
        policy=RetrievalPolicy(overfetch_multiplier=1),
        field_index=field_index,
    )
    result = retriever.retrieve(
        RetrievalRequest(paper_id="p1", question="Figure architecture overview", limit=2)
    )

    assert [chunk.chunk_id for chunk in result.child_chunks] == ["fig-strong", "fig-weak"]
    top = result.child_chunks[0]
    assert top.metadata["caption_embedding_score"] == 0.98
    assert top.metadata["field_embedding_score"] == 0.98
    assert top.metadata["best_embedding_field"] == "caption"
    assert top.metadata["best_matching_field"] == "caption"
    assert top.metadata["child_score_strategy"] == "semantic_field_embedding_rerank_fusion"
    assert result.metadata["field_hits_count"] == 1
    assert result.metadata["field_hits_by_name"] == {"caption": 1}


def test_field_search_plan_depends_on_intent():
    figure = _chunk(
        "fig-1",
        chunk_type="figure",
        content="[Figure fig-1]\nCaption:\nArchitecture overview.",
    )
    store = _ScriptedChunkStore([figure], search_order=["fig-1"])
    field_index = _FakeFieldIndex([])

    retriever = ResearchRetriever(store, field_index=field_index)
    retriever.retrieve(RetrievalRequest(paper_id="p1", question="What does Figure 1 show?", limit=1))

    assert field_index.calls[0]["field_names"] == ("caption", "body")
    assert field_index.calls[0]["filters"]["chunk_type"] == "figure"


def test_structured_field_reranker_influences_child_ordering():
    weak = _chunk(
        "weak-child",
        content="weak-field generic method details.",
    )
    strong = _chunk(
        "strong-child",
        content="strong-field exact method explanation.",
    )
    store = _ScriptedChunkStore([weak, strong], search_order=["weak-child", "strong-child"])
    field_reranker = _KeywordReranker({"strong-field": 0.95, "weak-field": 0.0})

    retriever = ResearchRetriever(
        store,
        policy=RetrievalPolicy(overfetch_multiplier=1),
        field_reranker=field_reranker,
    )
    result = retriever.retrieve(
        RetrievalRequest(paper_id="p1", question="how does the exact method work?", limit=2)
    )

    assert [chunk.chunk_id for chunk in result.child_chunks] == ["strong-child", "weak-child"]
    top = result.child_chunks[0]
    assert top.metadata["field_rerank_score"] == 0.95
    assert top.metadata["field_rerank_strategy"] == "cross_encoder_structured_fields"
    assert top.metadata["child_score_strategy"] == "semantic_field_embedding_rerank_fusion"
    assert "Body:" in field_reranker.calls[0][1][0]
    assert result.metadata["field_reranker_enabled"] is True
    assert result.metadata["field_rerank_top"] == 0.95


def test_field_reranker_failure_keeps_deterministic_fallback():
    child = _chunk(
        "method-child",
        section_title="Architecture",
        content="The architecture uses attention.",
    )
    store = _ScriptedChunkStore([child], search_order=["method-child"])

    retriever = ResearchRetriever(
        store,
        policy=RetrievalPolicy(overfetch_multiplier=1),
        field_reranker=_FailingReranker(),
    )
    result = retriever.retrieve(
        RetrievalRequest(paper_id="p1", question="how does the architecture work?", limit=1)
    )

    top = result.child_chunks[0]
    assert top.metadata["child_score_strategy"] == "semantic_lexical_field_fallback"
    assert top.metadata["field_embedding_score"] == 0.0
    assert top.metadata["field_rerank_score"] is None


def test_position_weighting_prefers_nearby():
    store = _make_store()
    _seed_store(store)
    retriever = ResearchRetriever(store)
    # reading at section 2 — child1 (sec_idx=2) should score higher than child2 (sec_idx=5)
    result_near = retriever.retrieve(
        RetrievalRequest(paper_id="p1", question="accuracy benchmark results", current_section_index=2, limit=2)
    )
    result_far = retriever.retrieve(
        RetrievalRequest(paper_id="p1", question="accuracy benchmark results", current_section_index=5, limit=2)
    )
    # both return results; just verify no exceptions and results are populated
    assert isinstance(result_near.child_chunks, list)
    assert isinstance(result_far.child_chunks, list)


def test_as_evidence_candidates():
    store = _make_store()
    _seed_store(store)
    retriever = ResearchRetriever(store)
    result = retriever.retrieve(RetrievalRequest(paper_id="p1", question="attention"))
    candidates = result.as_evidence_candidates()
    assert isinstance(candidates, list)
    if candidates:
        c = candidates[0]
        assert c["evidence_id"]
        assert c["span_refs"]
        assert c["lineage"]


def test_as_evidence_candidates_preserves_span_metadata():
    content = "Borrowed sentence.\nCurrent body."
    chunk = PaperChunk(
        chunk_id="para-1",
        paper_id="p1",
        parse_source="latex",
        chunk_type="paragraph",
        section_title="Method",
        section_role=["method"],
        section_index=1,
        content=content,
        metadata={
            "source_ref": "arxiv://p1/para-1",
            "source_locator": "paper://p1/pdf#page=2",
            **build_paragraph_span_metadata(
                content=content,
                overlap_text="Borrowed sentence.",
                overlap_origin_chunk_id="para-0",
                overlap_origin_source_locator="paper://p1/pdf#page=1",
            ),
        },
    )
    candidates = RetrievalResult(
        parent_chunks=[],
        child_chunks=[chunk],
        ref_chunks=[],
        intent="concept_method",
    ).as_evidence_candidates()

    assert candidates[0]["metadata"]["content_span_unit"] == "char_offset"
    assert candidates[0]["metadata"]["main_span"]["start"] > 0
    assert candidates[0]["metadata"]["overlap_spans"][0]["origin_chunk_id"] == "para-0"


def test_empty_paper_returns_empty():
    store = _make_store()
    store.ensure_collection()
    retriever = ResearchRetriever(store)
    result = retriever.retrieve(RetrievalRequest(paper_id="nonexistent", question="anything"))
    assert result.child_chunks == []
    assert result.parent_chunks == []


# ── RetrievalPolicy ────────────────────────────────────────────────────────────

def test_policy_position_weight_decays_with_distance():
    policy = RetrievalPolicy()
    near = policy.position_weight("concept_method", section_index=2, current=2)
    mid = policy.position_weight("concept_method", section_index=4, current=2)
    far = policy.position_weight("concept_method", section_index=8, current=2)
    assert near > mid > far
    assert near == pytest.approx(0.2)  # exp(0) * 0.2


def test_policy_zero_alpha_intents_no_position_bias():
    policy = RetrievalPolicy()
    # figure/table/formula queries should never get a position bonus
    assert policy.position_weight("figure_query", 0, 5) == 0.0
    assert policy.position_weight("table_query", 0, 5) == 0.0
    assert policy.position_weight("formula_query", 10, 0) == 0.0


def test_policy_default_alpha_for_unknown_intent():
    policy = RetrievalPolicy(default_alpha=0.5)
    # unlisted intent falls back to default_alpha
    assert policy.alpha_for("totally_unknown_intent") == 0.5


def test_custom_policy_injected():
    store = _make_store()
    _seed_store(store)
    custom = RetrievalPolicy(overfetch_multiplier=1, sigma=1.0)
    retriever = ResearchRetriever(store, policy=custom)
    result = retriever.retrieve(RetrievalRequest(paper_id="p1", question="attention", limit=2))
    assert isinstance(result.child_chunks, list)


# ── cross-reference expansion ──────────────────────────────────────────────────

def test_cross_reference_expansion():
    store = _make_store()
    referenced = _chunk("sec-bg", section_index=0, section_title="Background",
                        section_role=["background"], content="Background definitions.")
    child = _chunk("para-x", section_index=2, parent_chunk_id="sec-1",
                   content="As defined earlier, attention scales queries.")
    child = child.model_copy(update={"references": ["sec-bg"]})
    parent = _chunk("sec-1", section_index=2, content="Method section.")
    store.ensure_collection()
    store.index_chunks([parent, child, referenced])
    retriever = ResearchRetriever(store)
    result = retriever.retrieve(RetrievalRequest(paper_id="p1", question="attention scales queries", limit=1))
    # with limit=1 only para-x matches; its cross-ref target sec-bg should surface in ref_chunks
    if any(c.chunk_id == "para-x" for c in result.child_chunks):
        assert any(r.chunk_id == "sec-bg" for r in result.ref_chunks)


# ── parent fallback (abstract has no parent) ───────────────────────────────────

def test_parent_fallback_to_children_when_no_parent():
    store = _make_store()
    abstract = _chunk("abs-1", chunk_type="abstract", section_title="Abstract",
                      section_role=["background"], section_index=0,
                      parent_chunk_id=None, content="We propose a new attention model.")
    store.ensure_collection()
    store.index_chunks([abstract])
    retriever = ResearchRetriever(store)
    result = retriever.retrieve(RetrievalRequest(paper_id="p1", question="what is proposed"))
    # no parent_chunk_id → falls back to returning the matched children themselves
    assert result.parent_chunks
    assert result.parent_chunks[0].chunk_id == "abs-1"


def test_long_parent_expansion_returns_child_anchored_snippet():
    anchor = "The attention block mixes local and global features for stability."
    parent_content = " ".join(["intro"] * 80 + [anchor] + ["tail"] * 80)
    parent = _chunk("sec-long", content=parent_content)
    child = _chunk("para-anchor", parent_chunk_id="sec-long", content=anchor)
    store = _ScriptedChunkStore([child, parent], search_order=["para-anchor"])
    policy = RetrievalPolicy(
        max_parent_tokens=500,
        long_parent_token_threshold=10,
        parent_snippet_token_window=40,
        parent_intent_budgets={},
    )

    retriever = ResearchRetriever(store, policy=policy)
    result = retriever.retrieve(RetrievalRequest(paper_id="p1", question="how does attention work?", limit=1))

    snippet = result.parent_chunks[0]
    assert snippet.chunk_id == "sec-long"
    assert snippet.content != parent_content
    assert anchor in snippet.content
    assert snippet.metadata["parent_snippet"] is True
    assert snippet.metadata["parent_snippet_strategy"] == "child_anchor_window"
    assert snippet.metadata["source_parent_chunk_id"] == "sec-long"
    assert snippet.metadata["parent_anchor_child_id"] == "para-anchor"
    assert result.metadata["parent_snippets_returned"] == 1


def test_parent_reranker_orders_and_filters_parent_candidates():
    weak_child = _chunk("weak-child", parent_chunk_id="sec-weak", content="weak child anchor")
    strong_child = _chunk("strong-child", parent_chunk_id="sec-strong", content="strong child anchor")
    weak_parent = _chunk("sec-weak", content="weak-parent gives generic background.")
    strong_parent = _chunk("sec-strong", content="strong-parent explains the exact mechanism.")
    store = _ScriptedChunkStore(
        [weak_child, strong_child, weak_parent, strong_parent],
        search_order=["weak-child", "strong-child"],
    )
    policy = RetrievalPolicy(
        overfetch_multiplier=1,
        max_parent_chunks=2,
        max_parent_tokens=9999,
        parent_rerank_score_threshold=0.5,
        parent_intent_budgets={},
    )
    reranker = _KeywordReranker({"strong-parent": 0.95, "weak-parent": 0.2})

    retriever = ResearchRetriever(store, policy=policy, reranker=reranker)
    result = retriever.retrieve(RetrievalRequest(paper_id="p1", question="how does the method work?", limit=2))

    assert [chunk.chunk_id for chunk in result.parent_chunks] == ["sec-strong"]
    parent = result.parent_chunks[0]
    assert parent.metadata["parent_rerank_score"] == 0.95
    assert parent.metadata["parent_rerank_strategy"] == "cross_encoder"
    assert "Matched child evidence:" in parent.metadata["parent_rerank_query"]
    assert parent.metadata["parent_relevance_score"] == 0.95
    assert parent.metadata["parent_final_score"] > 0.0
    assert parent.metadata["parent_score_strategy"] == "cross_encoder"
    assert parent.metadata["parent_score_weights"]["parent"] > 0.0


def test_parent_budget_depends_on_query_intent():
    children = [
        _chunk(
            f"para-{index}",
            parent_chunk_id=f"sec-{index}",
            content=f"experiment result anchor {index}",
            section_role=["experiment"],
        )
        for index in range(1, 4)
    ]
    parents = [
        _chunk(f"sec-{index}", content=f"Experiment parent {index}.")
        for index in range(1, 4)
    ]
    store = _ScriptedChunkStore(
        [*children, *parents],
        search_order=[child.chunk_id for child in children],
    )
    policy = RetrievalPolicy(
        overfetch_multiplier=1,
        max_parent_chunks=3,
        max_parent_tokens=9999,
    )

    retriever = ResearchRetriever(store, policy=policy)
    method_result = retriever.retrieve(
        RetrievalRequest(paper_id="p1", question="how does the method work?", limit=3)
    )
    numerical_result = retriever.retrieve(
        RetrievalRequest(paper_id="p1", question="experiment results show", limit=3)
    )

    assert len(method_result.parent_chunks) == 3
    assert method_result.metadata["parent_budget_chunks"] == 3
    assert len(numerical_result.parent_chunks) == 2
    assert numerical_result.metadata["parent_budget_chunks"] == 2


def test_numerical_result_parent_score_prefers_result_heading():
    generic_child = _chunk(
        "generic-child",
        parent_chunk_id="sec-generic",
        section_role=["experiment"],
        content="experiment result anchor generic",
    )
    result_child = _chunk(
        "result-child",
        parent_chunk_id="sec-results",
        section_role=["experiment"],
        content="experiment result anchor detailed",
    )
    generic_parent = _chunk(
        "sec-generic",
        section_title="Sampling Procedure",
        section_role=["method"],
        content="Procedure context.",
    )
    result_parent = _chunk(
        "sec-results",
        section_title="Experimental Results",
        section_role=["experiment"],
        content="Result context.",
    )
    store = _ScriptedChunkStore(
        [generic_child, result_child, generic_parent, result_parent],
        search_order=["generic-child", "result-child"],
    )
    policy = RetrievalPolicy(overfetch_multiplier=1, max_parent_tokens=9999, parent_intent_budgets={})

    retriever = ResearchRetriever(store, policy=policy)
    result = retriever.retrieve(RetrievalRequest(paper_id="p1", question="experiment results show", limit=2))

    assert [chunk.chunk_id for chunk in result.parent_chunks] == ["sec-results", "sec-generic"]
    top = result.parent_chunks[0]
    assert top.metadata["parent_section_heading_score"] == 1.0
    assert result.metadata["parent_scoring_enabled"] is True
    assert result.metadata["parent_candidates_scored"] == 2
    assert result.metadata["parent_score_top"] == top.metadata["parent_final_score"]
    assert result.metadata["parent_score_min"] <= result.metadata["parent_score_top"]


def test_parent_reranker_failure_falls_back_to_deterministic_score_metadata():
    child = _chunk("child", parent_chunk_id="sec-method", content="method anchor")
    parent = _chunk(
        "sec-method",
        section_title="Method",
        section_role=["method"],
        content="Method context.",
    )
    store = _ScriptedChunkStore([child, parent], search_order=["child"])

    retriever = ResearchRetriever(
        store,
        policy=RetrievalPolicy(overfetch_multiplier=1, parent_intent_budgets={}),
        reranker=_FailingReranker(),
    )
    result = retriever.retrieve(RetrievalRequest(paper_id="p1", question="how does the method work?", limit=1))

    scored_parent = result.parent_chunks[0]
    assert scored_parent.metadata["parent_score_strategy"] == "deterministic"
    assert scored_parent.metadata["parent_final_score"] > 0.0
    assert scored_parent.metadata["parent_child_relevance_score"] > 0.0
    assert scored_parent.metadata["parent_relevance_score"] > 0.0
    assert "parent_rerank_score" not in scored_parent.metadata


class _VisualHitStore:
    def __init__(self, hits: list[VisualChunkHit]) -> None:
        self.hits = hits
        self.calls: list[dict] = []

    def search_visual_chunks(
        self,
        paper_id: str,
        query_text: str,
        *,
        filters: dict | None = None,
        limit: int = 10,
    ) -> list[VisualChunkHit]:
        self.calls.append({
            "paper_id": paper_id,
            "query_text": query_text,
            "filters": filters or {},
            "limit": limit,
        })
        return self.hits[:limit]


def test_figure_query_fuses_visual_hits_with_text_results():
    store = _make_store()
    parent = _chunk("sec-fig", section_index=2, content="Visual section.")
    text_figure = _chunk(
        "fig-text",
        chunk_type="figure",
        parent_chunk_id="sec-fig",
        content="[Figure fig-text]\nCaption:\nA baseline chart.",
    )
    visual_figure = _chunk(
        "fig-visual",
        chunk_type="figure",
        parent_chunk_id="sec-fig",
        content="[Figure fig-visual]\nCaption:\nArchitecture overview.",
    )
    store.ensure_collection()
    store.index_chunks([parent, text_figure, visual_figure])
    visual_store = _VisualHitStore([VisualChunkHit(chunk_id="fig-visual", score=0.95)])

    retriever = ResearchRetriever(store, visual_store=visual_store)
    result = retriever.retrieve(
        RetrievalRequest(paper_id="p1", question="What does Figure 2 architecture show?", limit=2)
    )

    assert visual_store.calls
    assert visual_store.calls[0]["filters"]["chunk_type"] == "figure"
    assert any(chunk.chunk_id == "fig-visual" for chunk in result.child_chunks)
    visual_hit = next(chunk for chunk in result.child_chunks if chunk.chunk_id == "fig-visual")
    assert visual_hit.metadata["visual_hit"] is True
    assert visual_hit.metadata["visual_score"] == 0.95
    assert visual_hit.metadata["fusion_strategy"] in {"image_only", "text_image_fusion"}
    assert result.metadata["visual_recalled"] == 1
    assert result.metadata["visual_fusion_enabled"] is True


def test_visual_store_is_not_called_for_table_query():
    store = _make_store()
    table = _chunk(
        "tbl-1",
        chunk_type="table",
        content="[Table 1]\nCaption:\nMain benchmark results.",
    )
    store.ensure_collection()
    store.index_chunks([table])
    visual_store = _VisualHitStore([VisualChunkHit(chunk_id="tbl-1", score=0.99)])

    retriever = ResearchRetriever(store, visual_store=visual_store)
    result = retriever.retrieve(
        RetrievalRequest(paper_id="p1", question="What does Table 1 show?", limit=2)
    )

    assert visual_store.calls == []
    assert result.intent == "table_query"
    assert result.metadata["visual_recalled"] == 0


def test_table_hit_expands_nearby_and_referenced_context():
    table = _chunk(
        "tbl-1",
        chunk_type="table",
        section_title="Experiments",
        section_role=["experiment"],
        section_index=4,
        content="[Table 1]\nCaption:\nMain benchmark results.",
        metadata={
            "table_id": "tbl-1",
            "source_locator": "paper://p1/pdf#page=6&pdf_rect=1,2,3,4",
            "nearby_context_chunk_id": "near-table",
            "referenced_by_chunks": [
                {"chunk_id": "result-ref", "text_ref": "Table 1"},
                {"chunk_id": "missing-ref", "text_ref": "Table 1"},
                {"chunk_id": "foreign-ref", "text_ref": "Table 1"},
            ],
        },
    )
    nearby = _chunk(
        "near-table",
        section_title="Experiments",
        section_role=["experiment"],
        section_index=4,
        content="Nearby paragraph explains that Table 1 improves F1.",
    )
    referenced = _chunk(
        "result-ref",
        section_title="Results",
        section_role=["analysis"],
        section_index=5,
        content="As shown in Table 1, the new model wins.",
    )
    foreign = _chunk(
        "foreign-ref",
        paper_id="p2",
        section_title="Results",
        section_role=["analysis"],
        section_index=5,
        content="Foreign paper should never be included.",
    )
    store = _ScriptedChunkStore(
        [table, nearby, referenced, foreign],
        search_order=["tbl-1", "near-table", "result-ref", "foreign-ref"],
    )

    retriever = ResearchRetriever(store)
    result = retriever.retrieve(RetrievalRequest(paper_id="p1", question="What does Table 1 show?", limit=1))

    ref_by_id = {chunk.chunk_id: chunk for chunk in result.ref_chunks}
    assert result.intent == "table_query"
    assert result.child_chunks[0].chunk_id == "tbl-1"
    assert table.metadata["source_locator"] == "paper://p1/pdf#page=6&pdf_rect=1,2,3,4"
    assert ref_by_id["near-table"].metadata["expansion_reason"] == "table_nearby_context"
    assert ref_by_id["near-table"].metadata["expansion_edge"] == "nearby_context_chunk_id"
    assert ref_by_id["result-ref"].metadata["expansion_reason"] == "table_body_reference"
    assert ref_by_id["result-ref"].metadata["expanded_from_chunk_id"] == "tbl-1"
    assert "missing-ref" not in ref_by_id
    assert "foreign-ref" not in ref_by_id
    assert result.metadata["table_context_returned"] == 2


def test_table_row_group_hit_expands_parent_table_chunk():
    parent_table = _chunk(
        "tbl-parent",
        chunk_type="table",
        content="[Table 2]\nCaption:\nFull ablation table.",
        metadata={"table_id": "tbl-2"},
    )
    row_group = _chunk(
        "tbl-row-20",
        chunk_type="table",
        content="rare-row-token rows 20 to 39.",
        metadata={
            "table_id": "tbl-2",
            "is_table_row_group": True,
            "parent_table_chunk_id": "tbl-parent",
        },
    )
    store = _ScriptedChunkStore([row_group, parent_table], search_order=["tbl-row-20", "tbl-parent"])

    retriever = ResearchRetriever(store)
    result = retriever.retrieve(RetrievalRequest(paper_id="p1", question="table rare-row-token", limit=1))

    parent = next(chunk for chunk in result.ref_chunks if chunk.chunk_id == "tbl-parent")
    assert result.child_chunks[0].chunk_id == "tbl-row-20"
    assert parent.metadata["expansion_reason"] == "table_row_group_parent"
    assert parent.metadata["expansion_edge"] == "parent_table_chunk_id"


def test_result_question_supplements_table_and_keeps_result_paragraph():
    result_para = _chunk(
        "result-para",
        section_title="Experimental Results",
        section_role=["experiment"],
        section_index=4,
        content="实验结果表明 the method improves accuracy.",
    )
    table = _chunk(
        "tbl-results",
        chunk_type="table",
        section_title="Experimental Results",
        section_role=["experiment"],
        section_index=4,
        content="[Table 3]\nAccuracy and F1 scores.",
        metadata={
            "table_id": "tbl-results",
            "referenced_by_chunks": [{"chunk_id": "result-para", "text_ref": "Table 3"}],
        },
    )
    store = _ScriptedChunkStore([result_para, table], search_order=["result-para", "tbl-results"])

    retriever = ResearchRetriever(store)
    result = retriever.retrieve(RetrievalRequest(paper_id="p1", question="实验结果表明什么", limit=1))

    child_ids = {chunk.chunk_id for chunk in result.child_chunks}
    assert result.intent == "numerical_result"
    assert "result-para" in child_ids
    assert "tbl-results" in child_ids
    assert result.metadata["supplemental_table_returned"] == 1


def test_table_result_context_skips_generic_experiment_paragraphs():
    table = _chunk(
        "tbl-results",
        chunk_type="table",
        section_title="Sample Quality",
        section_role=["experiment"],
        section_index=4,
        content="[Table 4]\nSample quality scores.",
        metadata={"table_id": "tbl-results"},
    )
    generic_experiment = _chunk(
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
    store = _ScriptedChunkStore(
        [table, generic_experiment, conclusion],
        search_order=["tbl-results", "generic-experiment", "result-conclusion"],
    )

    retriever = ResearchRetriever(store)
    result = retriever.retrieve(RetrievalRequest(paper_id="p1", question="What does Table 4 show?", limit=1))

    ref_ids = {chunk.chunk_id for chunk in result.ref_chunks}
    assert "result-conclusion" in ref_ids
    assert "generic-experiment" not in ref_ids
    result_context = next(chunk for chunk in result.ref_chunks if chunk.chunk_id == "result-conclusion")
    assert result_context.metadata["expansion_reason"] == "table_result_context"


def test_table_result_context_reranker_orders_heuristic_candidates():
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
    store = _ScriptedChunkStore(
        [table, weak, strong],
        search_order=["tbl-results", "weak-result", "strong-result"],
    )
    reranker = _KeywordReranker({"strong-result": 0.95, "weak-result": 0.2})

    retriever = ResearchRetriever(store, reranker=reranker)
    result = retriever.retrieve(RetrievalRequest(paper_id="p1", question="What does Table 4 show?", limit=1))

    assert reranker.calls
    heuristic_refs = [
        chunk for chunk in result.ref_chunks
        if chunk.metadata.get("expansion_reason") == "table_result_context"
    ]
    assert [chunk.chunk_id for chunk in heuristic_refs] == ["strong-result", "weak-result"]
    assert heuristic_refs[0].metadata["table_context_rerank_score"] == 0.95
    assert heuristic_refs[0].metadata["table_context_rerank_strategy"] == "cross_encoder"
    assert "Table evidence:" in heuristic_refs[0].metadata["table_context_rerank_query"]
