from __future__ import annotations

from typing import Any

from business.research.document.models import PaperChunk
from business.research.ports.visual_chunk_index import VisualChunkHit
from business.research.rag.retrieval.channels.visual import VisualRecallChannel
from business.research.rag.retrieval.paper_policy import RetrievalRoute
from business.research.rag.retrieval.paper_retriever import RetrievalPolicy, RetrievalRequest
from business.research.rag.retrieval.ranking_stage import ChildRankingStage
from business.research.rag.retrieval.scoring import ChildCandidateScorer


def _chunk(
    chunk_id: str,
    *,
    content: str = "The method uses attention.",
    chunk_type: str = "paragraph",
    metadata: dict[str, Any] | None = None,
) -> PaperChunk:
    return PaperChunk(
        chunk_id=chunk_id,
        paper_id="p1",
        parse_source="latex",
        chunk_type=chunk_type,  # type: ignore[arg-type]
        section_title="Method",
        section_role=["method"],  # type: ignore[arg-type]
        section_index=1,
        content=content,
        metadata=metadata or {},
    )


class _RerankCascade:
    def __init__(
        self,
        *,
        base_enabled: bool = False,
        field_enabled: bool = False,
        base_scores: list[float] | None = None,
        field_scores: dict[str, float] | None = None,
    ) -> None:
        self._base_enabled = base_enabled
        self._field_enabled = field_enabled
        self._base_scores = base_scores
        self._field_scores = field_scores or {}
        self.field_score_chunks: list[list[str]] = []

    def base_enabled_for(self, intent: str) -> bool:
        return self._base_enabled

    def field_enabled_for(self, intent: str) -> bool:
        return self._field_enabled

    def base_scores(
        self,
        question: str,
        candidates: list[tuple[PaperChunk, float]],
        *,
        intent: str,
    ) -> list[float]:
        if self._base_scores is not None:
            return self._base_scores
        return [score for _chunk, score in candidates]

    def field_scores(
        self,
        question: str,
        chunks: list[PaperChunk],
        *,
        intent: str,
    ) -> dict[str, float]:
        self.field_score_chunks.append([chunk.chunk_id for chunk in chunks])
        return dict(self._field_scores)


class _ChunkStore:
    def __init__(self, chunks: list[PaperChunk]) -> None:
        self._chunks = {chunk.chunk_id: chunk for chunk in chunks}

    def get_chunk(self, chunk_id: str) -> PaperChunk | None:
        return self._chunks.get(chunk_id)


def _stage(
    policy: RetrievalPolicy,
    rerank_cascade: _RerankCascade,
    *,
    chunks: list[PaperChunk] | None = None,
) -> ChildRankingStage:
    return ChildRankingStage(
        policy=policy,
        rerank_cascade=rerank_cascade,
        child_scorer=ChildCandidateScorer(policy),
        visual_channel=VisualRecallChannel(_ChunkStore(chunks or []), None),
        request_factory=RetrievalRequest,
    )


def test_threshold_filter_keeps_fallback_candidate_when_all_scores_are_low() -> None:
    first = _chunk("first")
    second = _chunk("second")
    policy = RetrievalPolicy(
        reranking_intents=("concept_method",),
        rerank_score_threshold=0.9,
        field_scoring_enabled=False,
    )
    rerank = _RerankCascade(base_enabled=True, base_scores=[0.1, 0.2])
    result = _stage(policy, rerank).rank(
        RetrievalRequest(paper_id="p1", question="how does the method work?", limit=5),
        RetrievalRoute(intent="concept_method"),
        [(first, 0.6), (second, 0.5)],
        [],
        limit=5,
    )

    assert result.base_reranker_enabled is True
    assert result.n_filtered == 1
    assert [chunk.chunk_id for chunk in result.child_chunks] == ["first"]
    assert result.scored[0][0].metadata["fusion_strategy"] == "text"


def test_field_rerank_scores_are_applied_to_child_score_metadata() -> None:
    weak = _chunk("weak", content="generic method")
    strong = _chunk("strong", content="exact transformer method")
    policy = RetrievalPolicy(
        field_reranking_intents=("concept_method",),
        field_scoring_enabled=False,
    )
    rerank = _RerankCascade(
        field_enabled=True,
        base_scores=[0.5, 0.5],
        field_scores={"weak": 0.1, "strong": 0.95},
    )
    result = _stage(policy, rerank).rank(
        RetrievalRequest(paper_id="p1", question="exact transformer method", limit=2),
        RetrievalRoute(intent="concept_method"),
        [(weak, 0.5), (strong, 0.5)],
        [],
        limit=2,
    )

    assert result.field_reranker_enabled is True
    assert result.field_rerank_scores == {"weak": 0.1, "strong": 0.95}
    assert rerank.field_score_chunks == [["weak", "strong"]]
    assert [chunk.chunk_id for chunk in result.child_chunks] == ["strong", "weak"]
    assert result.child_chunks[0].metadata["field_rerank_score"] == 0.95
    assert result.child_chunks[0].metadata["field_rerank_strategy"] == "cross_encoder_structured_fields"


def test_visual_hits_are_fused_and_preserve_visual_metadata() -> None:
    text_figure = _chunk(
        "fig-text",
        chunk_type="figure",
        content="[Figure 1]\nCaption:\nA baseline chart.",
    )
    visual_figure = _chunk(
        "fig-visual",
        chunk_type="figure",
        content="[Figure 2]\nCaption:\nArchitecture overview.",
    )
    policy = RetrievalPolicy(field_scoring_enabled=False)
    rerank = _RerankCascade(base_scores=[0.5])
    result = _stage(policy, rerank, chunks=[text_figure, visual_figure]).rank(
        RetrievalRequest(paper_id="p1", question="architecture figure", limit=2),
        RetrievalRoute(intent="figure_query"),
        [(text_figure, 0.5)],
        [VisualChunkHit("fig-text", 1.0), VisualChunkHit("fig-visual", 0.8)],
        limit=2,
    )

    by_id = {chunk.chunk_id: chunk for chunk in result.child_chunks}
    assert set(by_id) == {"fig-text", "fig-visual"}
    assert by_id["fig-text"].metadata["visual_hit"] is True
    assert by_id["fig-text"].metadata["visual_score"] == 1.0
    assert by_id["fig-text"].metadata["fusion_strategy"] == "text_image_fusion"
    assert by_id["fig-visual"].metadata["visual_hit"] is True
    assert by_id["fig-visual"].metadata["fusion_strategy"] == "image_only"
