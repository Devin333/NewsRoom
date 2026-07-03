from __future__ import annotations

from typing import Any

from business.research.document.models import PaperChunk
from business.research.ports.field_embedding_index import FieldEmbeddingHit
from business.research.ports.visual_chunk_index import VisualChunkHit
from business.research.rag.retrieval import CandidateRecallStage
from business.research.rag.retrieval.channels.claim_index import ClaimIndexChannel
from business.research.rag.retrieval.channels.dense_text import DenseTextChannel
from business.research.rag.retrieval.channels.field_embedding import FieldEmbeddingChannel
from business.research.rag.retrieval.channels.sparse_lexical import SparseLexicalChannel
from business.research.rag.retrieval.channels.visual import VisualRecallChannel
from business.research.rag.retrieval.paper_claim_index import ClaimRecord, ClaimSearchHit
from business.research.rag.retrieval.paper_policy import RetrievalRoute
from business.research.rag.retrieval.paper_retriever import RetrievalPolicy, RetrievalRequest
from business.research.rag.retrieval.trace import RetrievalTrace


def _chunk(
    chunk_id: str,
    content: str = "The paper describes multi-head attention.",
    *,
    paper_id: str = "p1",
    chunk_type: str = "paragraph",
    section_title: str = "Method",
) -> PaperChunk:
    return PaperChunk(
        chunk_id=chunk_id,
        paper_id=paper_id,
        parse_source="latex",
        chunk_type=chunk_type,  # type: ignore[arg-type]
        section_title=section_title,
        section_role=["method"],
        section_index=1,
        has_figure=chunk_type == "figure",
        has_table=chunk_type == "table",
        content=content,
        metadata={},
    )


def _claim_hit(chunk_id: str, score: float = 0.9) -> ClaimSearchHit:
    return ClaimSearchHit(
        record=ClaimRecord(
            claim_id=f"claim-{chunk_id}",
            paper_id="p1",
            chunk_id=chunk_id,
            section_title="Results",
            claim_text="The model improves accuracy.",
            source_locator="paper://p1#page=3",
            claim_type="result",
        ),
        score=score,
    )


class _ChunkStore:
    def __init__(
        self,
        chunks: list[PaperChunk],
        *,
        search_order: list[str] | None = None,
        scores: dict[str, float] | None = None,
    ) -> None:
        self._chunks = {chunk.chunk_id: chunk for chunk in chunks}
        self._search_order = search_order or [chunk.chunk_id for chunk in chunks]
        self._scores = scores or {}
        self.calls: list[dict[str, Any]] = []

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
        return [
            chunk
            for chunk, _score in self.search_with_scores(
                paper_id,
                query_text,
                filters=filters,
                limit=limit,
            )
        ]

    def search_with_scores(
        self,
        paper_id: str,
        query_text: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 30,
    ) -> list[tuple[PaperChunk, float]]:
        self.calls.append({
            "paper_id": paper_id,
            "query_text": query_text,
            "filters": filters,
            "limit": limit,
        })
        out: list[tuple[PaperChunk, float]] = []
        for index, chunk_id in enumerate(self._search_order):
            chunk = self._chunks[chunk_id]
            if chunk.paper_id != paper_id or not _matches_filters(chunk, filters or {}):
                continue
            score = self._scores.get(chunk_id, 1.0 - (index / 100.0))
            out.append((chunk, score))
            if len(out) >= limit:
                break
        return out

    def get_chunk(self, chunk_id: str) -> PaperChunk | None:
        return self._chunks.get(chunk_id)

    def get_parent_chunk(self, chunk: PaperChunk) -> PaperChunk | None:
        if not chunk.parent_chunk_id:
            return None
        return self.get_chunk(chunk.parent_chunk_id)

    def list_chunks(self, paper_id: str) -> list[PaperChunk]:
        return [chunk for chunk in self._chunks.values() if chunk.paper_id == paper_id]


class _FieldIndex:
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
            "filters": filters,
            "limit": limit,
        })
        return self.hits[:limit]


class _ClaimIndex:
    def __init__(self, hits: list[ClaimSearchHit]) -> None:
        self.hits = hits

    def search_claims(self, paper_id: str, query_text: str, *, limit: int) -> list[ClaimSearchHit]:
        return self.hits[:limit]


class _VisualStore:
    def __init__(self, hits: list[VisualChunkHit]) -> None:
        self.hits = hits

    def search_visual_chunks(
        self,
        paper_id: str,
        query_text: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> list[VisualChunkHit]:
        return self.hits[:limit]


def _stage(
    store: _ChunkStore,
    policy: RetrievalPolicy,
    *,
    field_index: _FieldIndex | None = None,
    claim_index: _ClaimIndex | None = None,
    visual_store: _VisualStore | None = None,
) -> CandidateRecallStage:
    return CandidateRecallStage(
        dense_channel=DenseTextChannel(store),
        sparse_channel=SparseLexicalChannel(store),
        field_channel=FieldEmbeddingChannel(store, field_index),
        claim_channel=ClaimIndexChannel(store, claim_index),
        visual_channel=VisualRecallChannel(store, visual_store),
        field_index=field_index,
        claim_index=claim_index,
        visual_store=visual_store,
        policy=policy,
    )


def _trace() -> RetrievalTrace:
    return RetrievalTrace(policy_name="test", policy_hash="hash")


def _matches_filters(chunk: PaperChunk, filters: dict[str, Any]) -> bool:
    for key, expected in filters.items():
        actual = getattr(chunk, key, None)
        if actual is None:
            actual = chunk.metadata.get(key)
        if actual != expected:
            return False
    return True


def test_candidate_recall_stage_returns_dense_candidates_and_query_variants() -> None:
    weak = _chunk("weak", "Generic method text.")
    strong = _chunk("strong", "Attention method text.")
    store = _ChunkStore([weak, strong], search_order=["strong", "weak"])
    stage = _stage(store, RetrievalPolicy())

    result = stage.recall(
        RetrievalRequest(paper_id="p1", question="What is the method?", limit=2),
        RetrievalRoute(intent="concept_method"),
        [{}],
        2,
        trace=_trace(),
    )

    assert [chunk.chunk_id for chunk, _score in result.candidates] == ["strong", "weak"]
    assert result.n_recalled == 2
    assert result.n_visual_recalled == 0
    assert result.query_variants == ["What is the method?"]
    assert result.field_hits == []
    assert result.claim_hits == []
    assert result.visual_hits == []


def test_candidate_recall_stage_hybrid_fuses_text_field_and_visual_channels(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("NEWS_ARTIFACT_ROOT", str(tmp_path / "runs"))
    dense = _chunk("fig-dense", "Architecture figure from dense recall.", chunk_type="figure")
    sparse = _chunk("fig-sparse", "Raremetric42 architecture figure.", chunk_type="figure")
    field = _chunk("fig-field", "Field-only visual result.", chunk_type="figure")
    visual = _chunk("fig-visual", "Visual-only result.", chunk_type="figure")
    store = _ChunkStore(
        [dense, sparse, field, visual],
        search_order=["fig-dense"],
        scores={"fig-dense": 0.95},
    )
    field_index = _FieldIndex([
        FieldEmbeddingHit(
            chunk_id="fig-field",
            field_name="caption",
            score=0.88,
            field_text="Architecture caption.",
        )
    ])
    visual_store = _VisualStore([VisualChunkHit("fig-visual", 0.77)])
    policy = RetrievalPolicy(
        hybrid_rrf_enabled=True,
        sparse_lexical_enabled=True,
        multi_query_enabled=True,
        overfetch_multiplier=2,
    )
    stage = _stage(store, policy, field_index=field_index, visual_store=visual_store)

    result = stage.recall(
        RetrievalRequest(paper_id="p1", question="Raremetric42 architecture figure", limit=3),
        RetrievalRoute(intent="figure_query"),
        [{"chunk_type": "figure"}],
        10,
        trace=_trace(),
    )

    ids = {chunk.chunk_id for chunk, _score in result.candidates}
    assert {"fig-dense", "fig-sparse", "fig-field", "fig-visual"} <= ids
    assert result.n_recalled >= 2
    assert result.n_visual_recalled == 1
    assert len(result.field_hits) == 1
    assert result.visual_hits == [VisualChunkHit("fig-visual", 0.77)]
    assert result.query_variants[0] == "Raremetric42 architecture figure"
    assert len(result.query_variants) > 1
    assert all(chunk.metadata.get("hybrid_rrf_fusion") for chunk, _score in result.candidates)


def test_candidate_recall_stage_hybrid_fuses_claim_channel() -> None:
    dense = _chunk("dense-claim", "The paper states a generic claim.")
    claim = _chunk("claim-only", "The model improves accuracy.")
    store = _ChunkStore([dense, claim], search_order=["dense-claim"])
    stage = _stage(
        store,
        RetrievalPolicy(hybrid_rrf_enabled=True),
        claim_index=_ClaimIndex([_claim_hit("claim-only", 0.92)]),
    )

    result = stage.recall(
        RetrievalRequest(
            paper_id="p1",
            question="Which evidence supports the claim that the model improves accuracy?",
            limit=2,
        ),
        RetrievalRoute(intent="citation_query"),
        [{"chunk_type": "paragraph"}],
        10,
        trace=_trace(),
    )

    by_id = {chunk.chunk_id: chunk for chunk, _score in result.candidates}
    assert "claim-only" in by_id
    assert by_id["claim-only"].metadata["claim_index_hit"] is True
    assert by_id["claim-only"].metadata["hybrid_rrf_fusion"] is True
    assert len(result.claim_hits) == 1


def test_candidate_recall_stage_optional_channels_absent_return_empty_hits() -> None:
    figure = _chunk("fig-1", "Architecture figure.", chunk_type="figure")
    store = _ChunkStore([figure])
    stage = _stage(store, RetrievalPolicy())

    result = stage.recall(
        RetrievalRequest(paper_id="p1", question="What does Figure 1 show?", limit=2),
        RetrievalRoute(intent="figure_query"),
        [{"chunk_type": "figure"}],
        2,
        trace=_trace(),
    )

    assert [chunk.chunk_id for chunk, _score in result.candidates] == ["fig-1"]
    assert result.field_hits == []
    assert result.claim_hits == []
    assert result.visual_hits == []
