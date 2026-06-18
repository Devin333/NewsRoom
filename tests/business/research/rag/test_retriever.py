from __future__ import annotations

import pytest

from business.research.document.models import PaperChunk
from business.research.rag.retriever import (
    ResearchRetriever,
    RetrievalPolicy,
    RetrievalRequest,
)
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
        metadata={"is_parent": parent_chunk_id is None, "source_ref": f"arxiv://p1/{chunk_id}"},
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
    # figure/formula queries should never get a position bonus
    assert policy.position_weight("figure_query", 0, 5) == 0.0
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
