from __future__ import annotations

from typing import TYPE_CHECKING

from business.research.document.models import PaperChunk
from business.research.ports.chunk_store import ChunkStorePort
from business.research.ports.field_embedding_index import FieldEmbeddingSearchPort
from business.research.ports.visual_chunk_index import VisualChunkSearchPort
from business.research.rag.retrieval.channels.claim_index import ClaimIndexChannel
from business.research.rag.retrieval.channels.dense_text import DenseTextChannel
from business.research.rag.retrieval.channels.field_embedding import FieldEmbeddingChannel
from business.research.rag.retrieval.channels.sparse_lexical import SparseLexicalChannel
from business.research.rag.retrieval.channels.visual import VisualRecallChannel
from business.research.rag.retrieval.contracts import RetrievalRequest, RetrievalResult
from business.research.rag.retrieval.expanders.cross_ref import CrossRefContextExpander
from business.research.rag.retrieval.expanders.parent import ParentContextExpander
from business.research.rag.retrieval.expanders.structural import StructuralContextExpander
from business.research.rag.retrieval.expanders.supplemental_table import SupplementalTableHitExpander
from business.research.rag.retrieval.expanders.table_context import TableContextExpander
from business.research.rag.retrieval.paper_claim_index import PaperClaimSearchPort
from business.research.rag.retrieval.pipeline import RetrievalPipeline
from business.research.rag.retrieval.planner import QueryPlanner
from business.research.rag.retrieval.policies import (
    DEFAULT_RETRIEVAL_POLICY,
    HIGH_VALUE_VISUAL_RESULT_INTENTS,
    LIGHTWEIGHT_FIELD_RERANK_INTENTS,
    NEWS_PAPER_RAG_POLICY_ENV,
    PAPER_BLIND_SEMANTIC_RAG_V1_POLICY,
    PAPER_FORMULA_RAG_V1_POLICY,
    PAPER_HYBRID_RRF_RAG_V1_POLICY,
    PAPER_VISUAL_RAG_TUNED_POLICY,
    RetrievalPolicy,
    build_retrieval_policy,
    build_retrieval_policy_from_env,
    retrieval_policy_enables_lightweight_reranker,
)
from business.research.rag.retrieval.ranking_stage import ChildRankingStage
from business.research.rag.retrieval.recall_stage import CandidateRecallStage
from business.research.rag.retrieval.rerank import RerankCascade
from business.research.rag.retrieval.scoring import ChildCandidateScorer

if TYPE_CHECKING:
    from business.research.ports.reranker import RerankerPort


class ResearchRetriever:
    """
    Agent-callable retrieval tool.

    Flow: intent classification -> vector search -> rerank -> context expansion.
    """

    def __init__(
        self,
        chunk_store: ChunkStorePort,
        *,
        policy: RetrievalPolicy | None = None,
        reranker: "RerankerPort | None" = None,
        field_index: FieldEmbeddingSearchPort | None = None,
        field_reranker: "RerankerPort | None" = None,
        visual_store: VisualChunkSearchPort | None = None,
        claim_index: PaperClaimSearchPort | None = None,
    ) -> None:
        self._store = chunk_store
        self._dense_channel = DenseTextChannel(chunk_store)
        self._sparse_channel = SparseLexicalChannel(chunk_store)
        self._field_channel = FieldEmbeddingChannel(chunk_store, field_index)
        self._claim_channel = ClaimIndexChannel(chunk_store, claim_index)
        self._visual_channel = VisualRecallChannel(chunk_store, visual_store)
        self._policy = policy or RetrievalPolicy()
        self._recall_stage = CandidateRecallStage(
            dense_channel=self._dense_channel,
            sparse_channel=self._sparse_channel,
            field_channel=self._field_channel,
            claim_channel=self._claim_channel,
            visual_channel=self._visual_channel,
            field_index=field_index,
            claim_index=claim_index,
            visual_store=visual_store,
            policy=self._policy,
        )
        planner = QueryPlanner(self._policy)
        rerank_cascade = RerankCascade(
            self._policy,
            reranker=reranker,
            field_reranker=field_reranker,
        )
        parent_expander = ParentContextExpander(
            chunk_store,
            self._policy,
            reranker=reranker,
        )
        cross_ref_expander = CrossRefContextExpander(chunk_store)
        table_context_expander = TableContextExpander(
            chunk_store,
            self._policy,
            reranker=reranker,
        )
        structural_expander = StructuralContextExpander(chunk_store, self._policy)
        supplemental_table_expander = SupplementalTableHitExpander(chunk_store, self._policy)
        child_scorer = ChildCandidateScorer(self._policy)
        ranking_stage = ChildRankingStage(
            policy=self._policy,
            rerank_cascade=rerank_cascade,
            child_scorer=child_scorer,
            visual_channel=self._visual_channel,
            request_factory=RetrievalRequest,
        )
        self._pipeline = RetrievalPipeline(
            policy=self._policy,
            planner=planner,
            recall_stage=self._recall_stage,
            ranking_stage=ranking_stage,
            parent_expander=parent_expander,
            cross_ref_expander=cross_ref_expander,
            table_context_expander=table_context_expander,
            structural_expander=structural_expander,
            supplemental_table_expander=supplemental_table_expander,
            result_factory=RetrievalResult,
            reranker_available=reranker is not None,
            field_index_available=field_index is not None,
            field_reranker_available=field_reranker is not None,
            visual_store_available=visual_store is not None,
            claim_index_available=claim_index is not None,
        )

    @property
    def policy(self) -> RetrievalPolicy:
        return self._policy

    def get_chunk(self, chunk_id: str) -> PaperChunk | None:
        """Expose deterministic chunk lookup for context assembly helpers."""
        return self._store.get_chunk(chunk_id)

    def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        return self._pipeline.retrieve(request)


__all__ = [
    "DEFAULT_RETRIEVAL_POLICY",
    "HIGH_VALUE_VISUAL_RESULT_INTENTS",
    "LIGHTWEIGHT_FIELD_RERANK_INTENTS",
    "NEWS_PAPER_RAG_POLICY_ENV",
    "PAPER_BLIND_SEMANTIC_RAG_V1_POLICY",
    "PAPER_FORMULA_RAG_V1_POLICY",
    "PAPER_HYBRID_RRF_RAG_V1_POLICY",
    "PAPER_VISUAL_RAG_TUNED_POLICY",
    "ResearchRetriever",
    "RetrievalPolicy",
    "RetrievalRequest",
    "RetrievalResult",
    "build_retrieval_policy",
    "build_retrieval_policy_from_env",
    "retrieval_policy_enables_lightweight_reranker",
]
