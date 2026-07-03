from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Mapping, TYPE_CHECKING

from framework.rag.core import intent_allowed, intent_budget, position_decay_score
from framework.rag.retrieval import dedupe_by_key

from business.research.document.models import PaperChunk
from business.research.ports.chunk_store import ChunkStorePort
from business.research.ports.field_embedding_index import FieldEmbeddingSearchPort
from business.research.ports.visual_chunk_index import VisualChunkSearchPort
from business.research.rag.adapters.paper_field_text import FIELD_NAMES
from business.research.rag.retrieval.channels.claim_index import ClaimIndexChannel
from business.research.rag.retrieval.channels.dense_text import DenseTextChannel
from business.research.rag.retrieval.channels.field_embedding import FieldEmbeddingChannel
from business.research.rag.retrieval.channels.sparse_lexical import SparseLexicalChannel
from business.research.rag.retrieval.channels.visual import VisualRecallChannel
from business.research.rag.retrieval.expanders.cross_ref import CrossRefContextExpander
from business.research.rag.retrieval.expanders.parent import ParentContextExpander
from business.research.rag.retrieval.expanders.structural import StructuralContextExpander
from business.research.rag.retrieval.expanders.supplemental_table import SupplementalTableHitExpander
from business.research.rag.retrieval.expanders.table_context import TableContextExpander
from business.research.rag.retrieval.paper_claim_index import PaperClaimSearchPort
from business.research.rag.retrieval.paper_policy import QueryIntent
from business.research.rag.retrieval.pipeline import RetrievalPipeline
from business.research.rag.retrieval.planner import QueryPlanner
from business.research.rag.retrieval.recall_stage import CandidateRecallStage
from business.research.rag.retrieval.rerank import RerankCascade
from business.research.rag.retrieval.scoring import (
    ChildCandidateScorer,
    normalized_child_fallback_score_weights,
    normalized_child_final_score_weights,
    normalized_field_score_weights,
    normalized_parent_score_weights,
)

if TYPE_CHECKING:
    from business.research.ports.reranker import RerankerPort

# Default position weight per intent (0 = no position bias)
_DEFAULT_ALPHA: dict[str, float] = {
    "figure_query":    0.0,
    "table_query":     0.0,
    "formula_query":   0.0,
    "contribution":    0.05,
    "concept_method":  0.2,
    "numerical_result": 0.2,
    "comparison":      0.2,
}

DEFAULT_RETRIEVAL_POLICY = "default"
PAPER_VISUAL_RAG_TUNED_POLICY = "paper_visual_rag_tuned"
PAPER_BLIND_SEMANTIC_RAG_V1_POLICY = "paper_blind_semantic_rag_v1"
PAPER_HYBRID_RRF_RAG_V1_POLICY = "paper_hybrid_rrf_rag_v1"
PAPER_FORMULA_RAG_V1_POLICY = "paper_formula_rag_v1"
NEWS_PAPER_RAG_POLICY_ENV = "NEWS_PAPER_RAG_POLICY"
HIGH_VALUE_VISUAL_RESULT_INTENTS = ("figure_query", "table_query", "numerical_result", "comparison")
LIGHTWEIGHT_FIELD_RERANK_INTENTS = (*HIGH_VALUE_VISUAL_RESULT_INTENTS, "formula_query")
@dataclass(frozen=True)
class RetrievalPolicy:
    """Tunable retrieval parameters (position weighting + over-fetch + rerank filter)."""
    name: str = DEFAULT_RETRIEVAL_POLICY
    position_alpha: dict[str, float] = field(default_factory=lambda: dict(_DEFAULT_ALPHA))
    default_alpha: float = 0.2          # fallback for unlisted intents
    sigma: float = 3.0                  # position decay rate, in sections
    overfetch_multiplier: int = 3       # fetch limit*N candidates before re-rank
    element_label_overfetch_multiplier: int = 25
    rerank_score_threshold: float = 0.3  # drop candidates below this reranker score (0 = off)
    visual_fusion_text_weight: float = 0.65
    visual_fusion_visual_weight: float = 0.35
    max_table_context_chunks: int = 4
    table_result_context_search_limit: int = 12
    supplemental_table_result_limit: int = 2
    max_figure_context_chunks: int = 2
    max_formula_context_chunks: int = 2
    citation_claim_overfetch_multiplier: int = 15
    citation_claim_boost: float = 0.35
    table_context_rerank_score_threshold: float = 0.0
    max_parent_chunks: int = 3
    max_parent_tokens: int = 1800
    long_parent_token_threshold: int = 900
    parent_snippet_token_window: int = 450
    parent_rerank_score_threshold: float = 0.0
    parent_intent_budgets: dict[str, tuple[int, int]] = field(default_factory=lambda: {
        "table_query": (1, 700),
        "formula_query": (1, 700),
        "numerical_result": (2, 1000),
        "comparison": (2, 1000),
    })
    parent_default_score_weights: dict[str, float] = field(default_factory=lambda: {
        "child": 0.45,
        "parent": 0.35,
        "heading": 0.15,
        "position": 0.05,
    })
    parent_intent_score_weights: dict[str, dict[str, float]] = field(default_factory=lambda: {
        "concept_method": {"child": 0.40, "parent": 0.30, "heading": 0.20, "position": 0.10},
        "contribution": {"child": 0.40, "parent": 0.30, "heading": 0.20, "position": 0.10},
        "numerical_result": {"child": 0.35, "parent": 0.40, "heading": 0.20, "position": 0.05},
        "comparison": {"child": 0.35, "parent": 0.40, "heading": 0.20, "position": 0.05},
        "table_query": {"child": 0.45, "parent": 0.25, "heading": 0.20, "position": 0.10},
        "formula_query": {"child": 0.45, "parent": 0.25, "heading": 0.20, "position": 0.10},
    })
    field_scoring_enabled: bool = True
    child_score_weights: dict[str, float] = field(default_factory=lambda: {
        "semantic": 0.60,
        "field": 0.25,
        "position": 0.10,
        "graph": 0.05,
    })
    child_final_score_weights: dict[str, float] = field(default_factory=lambda: {
        "semantic": 0.45,
        "field_embedding": 0.25,
        "field_rerank": 0.20,
        "position": 0.05,
        "graph": 0.05,
    })
    element_label_boosts: dict[str, float] = field(default_factory=dict)
    field_default_score_weights: dict[str, float] = field(default_factory=lambda: {
        "title": 0.25,
        "abstract": 0.15,
        "caption": 0.15,
        "equation": 0.15,
        "body": 0.30,
    })
    field_intent_score_weights: dict[str, dict[str, float]] = field(default_factory=lambda: {
        "concept_method": {"title": 0.35, "abstract": 0.15, "caption": 0.10, "equation": 0.10, "body": 0.30},
        "citation_query": {"title": 0.05, "abstract": 0.20, "caption": 0.00, "equation": 0.00, "body": 0.75},
        "contribution": {"title": 0.30, "abstract": 0.40, "caption": 0.05, "equation": 0.05, "body": 0.20},
        "figure_query": {"title": 0.10, "abstract": 0.05, "caption": 0.60, "equation": 0.05, "body": 0.20},
        "table_query": {"title": 0.10, "abstract": 0.05, "caption": 0.40, "equation": 0.05, "body": 0.40},
        "formula_query": {"title": 0.10, "abstract": 0.05, "caption": 0.05, "equation": 0.60, "body": 0.20},
        "numerical_result": {"title": 0.20, "abstract": 0.05, "caption": 0.25, "equation": 0.05, "body": 0.45},
        "comparison": {"title": 0.20, "abstract": 0.05, "caption": 0.20, "equation": 0.05, "body": 0.50},
    })
    field_embedding_enabled: bool = True
    field_reranking_enabled: bool = True
    reranking_intents: tuple[str, ...] = ()
    field_reranking_intents: tuple[str, ...] = ()
    sparse_lexical_enabled: bool = False
    hybrid_rrf_enabled: bool = False
    multi_query_enabled: bool = False
    rrf_k: int = 60
    sparse_search_limit_multiplier: int = 3
    field_embedding_search_limit_multiplier: int = 2
    formula_sparse_enabled: bool = False
    formula_sparse_boost: float = 0.0
    field_default_search_fields: tuple[str, ...] = FIELD_NAMES
    field_intent_search_fields: dict[str, tuple[str, ...]] = field(default_factory=lambda: {
        "concept_method": ("title", "abstract", "body", "caption"),
        "citation_query": ("body", "abstract", "title"),
        "contribution": ("abstract", "title", "body"),
        "figure_query": ("caption", "visual_description", "body"),
        "table_query": ("caption", "table_rows", "table_columns", "body"),
        "formula_query": ("equation", "referenced_text", "body"),
        "numerical_result": ("caption", "table_rows", "table_columns", "body", "title"),
        "comparison": ("caption", "table_rows", "table_columns", "body", "title"),
    })

    def alpha_for(self, intent: str) -> float:
        return self.position_alpha.get(intent, self.default_alpha)

    def position_weight(self, intent: str, section_index: int, current: int) -> float:
        return position_decay_score(
            section_index=section_index,
            current_index=current,
            alpha=self.alpha_for(intent),
            sigma=self.sigma,
        )

    def parent_budget_for(self, intent: str) -> tuple[int, int]:
        return intent_budget(
            intent,
            intent_budgets=self.parent_intent_budgets,
            default_budget=(self.max_parent_chunks, self.max_parent_tokens),
            max_chunks=self.max_parent_chunks,
            max_tokens=self.max_parent_tokens,
        )

    def parent_score_weights_for(self, intent: str) -> dict[str, float]:
        weights = dict(self.parent_default_score_weights)
        weights.update(self.parent_intent_score_weights.get(intent, {}))
        return normalized_parent_score_weights(weights)

    def field_score_weights_for(self, intent: str) -> dict[str, float]:
        weights = dict(self.field_default_score_weights)
        weights.update(self.field_intent_score_weights.get(intent, {}))
        return normalized_field_score_weights(weights)

    def normalized_child_score_weights(self) -> dict[str, float]:
        return normalized_child_fallback_score_weights(self.child_score_weights)

    def normalized_child_final_score_weights(self) -> dict[str, float]:
        return normalized_child_final_score_weights(self.child_final_score_weights)

    def field_search_fields_for(self, intent: str) -> tuple[str, ...]:
        fields = self.field_intent_search_fields.get(intent, self.field_default_search_fields)
        seen: set[str] = set()
        out: list[str] = []
        for field_name in fields:
            normalized = str(field_name).casefold()
            if normalized in FIELD_NAMES and normalized not in seen:
                out.append(normalized)
                seen.add(normalized)
        return tuple(out) if out else tuple(FIELD_NAMES)

    def reranker_enabled_for(self, intent: str) -> bool:
        return intent_allowed(intent, self.reranking_intents)

    def field_reranker_enabled_for(self, intent: str) -> bool:
        return self.field_reranking_enabled and intent_allowed(intent, self.field_reranking_intents)


def build_retrieval_policy(policy_name: str | None = None) -> RetrievalPolicy:
    """Build a named retrieval policy without changing the default behavior."""
    normalized = (policy_name or DEFAULT_RETRIEVAL_POLICY).strip().casefold()
    if not normalized or normalized == DEFAULT_RETRIEVAL_POLICY:
        return RetrievalPolicy()
    if normalized not in {
        PAPER_VISUAL_RAG_TUNED_POLICY,
        PAPER_BLIND_SEMANTIC_RAG_V1_POLICY,
        PAPER_HYBRID_RRF_RAG_V1_POLICY,
        PAPER_FORMULA_RAG_V1_POLICY,
    }:
        raise ValueError(
            f"unknown retrieval policy {policy_name!r}; expected "
            f"{DEFAULT_RETRIEVAL_POLICY!r}, {PAPER_VISUAL_RAG_TUNED_POLICY!r}, "
            f"{PAPER_BLIND_SEMANTIC_RAG_V1_POLICY!r}, {PAPER_HYBRID_RRF_RAG_V1_POLICY!r}, "
            f"or {PAPER_FORMULA_RAG_V1_POLICY!r}"
        )

    defaults = RetrievalPolicy()
    field_intent_score_weights = {
        intent: dict(weights)
        for intent, weights in defaults.field_intent_score_weights.items()
    }
    field_intent_score_weights["figure_query"] = {
        "title": 0.05,
        "abstract": 0.00,
        "caption": 0.75,
        "equation": 0.00,
        "body": 0.20,
    }
    field_intent_score_weights["table_query"] = {
        "title": 0.05,
        "abstract": 0.00,
        "caption": 0.45,
        "equation": 0.00,
        "body": 0.50,
    }
    child_final_score_weights = dict(defaults.child_final_score_weights)
    if normalized in {PAPER_BLIND_SEMANTIC_RAG_V1_POLICY, PAPER_HYBRID_RRF_RAG_V1_POLICY, PAPER_FORMULA_RAG_V1_POLICY}:
        child_final_score_weights = {
            "semantic": 0.35,
            "field_embedding": 0.25,
            "field_rerank": 0.30,
            "position": 0.00,
            "graph": 0.10,
        }
    if normalized == PAPER_FORMULA_RAG_V1_POLICY:
        field_intent_score_weights["formula_query"] = {
            "title": 0.05,
            "abstract": 0.00,
            "caption": 0.00,
            "equation": 0.75,
            "body": 0.20,
        }
    return RetrievalPolicy(
        name=normalized,
        overfetch_multiplier=5,
        visual_fusion_text_weight=0.85,
        visual_fusion_visual_weight=0.15,
        reranking_intents=HIGH_VALUE_VISUAL_RESULT_INTENTS,
        field_reranking_intents=LIGHTWEIGHT_FIELD_RERANK_INTENTS,
        element_label_boosts={
            "formula_query": 0.18,
            "table_query": 0.18,
            "figure_query": 0.12,
            "numerical_result": 0.12,
        },
        child_score_weights={
            "semantic": 0.45,
            "field": 0.40,
            "position": 0.05,
            "graph": 0.10,
        },
        child_final_score_weights=child_final_score_weights,
        field_intent_score_weights=field_intent_score_weights,
        sparse_lexical_enabled=normalized in {PAPER_HYBRID_RRF_RAG_V1_POLICY, PAPER_FORMULA_RAG_V1_POLICY},
        hybrid_rrf_enabled=normalized in {PAPER_HYBRID_RRF_RAG_V1_POLICY, PAPER_FORMULA_RAG_V1_POLICY},
        multi_query_enabled=normalized in {PAPER_HYBRID_RRF_RAG_V1_POLICY, PAPER_FORMULA_RAG_V1_POLICY},
        rrf_k=60,
        sparse_search_limit_multiplier=5 if normalized == PAPER_FORMULA_RAG_V1_POLICY else (
            4 if normalized == PAPER_HYBRID_RRF_RAG_V1_POLICY else 3
        ),
        formula_sparse_enabled=normalized == PAPER_FORMULA_RAG_V1_POLICY,
        formula_sparse_boost=0.20 if normalized == PAPER_FORMULA_RAG_V1_POLICY else 0.0,
        max_formula_context_chunks=4 if normalized == PAPER_FORMULA_RAG_V1_POLICY else defaults.max_formula_context_chunks,
    )


def retrieval_policy_enables_lightweight_reranker(policy_name: str | None) -> bool:
    return build_retrieval_policy(policy_name).name in {
        PAPER_BLIND_SEMANTIC_RAG_V1_POLICY,
        PAPER_HYBRID_RRF_RAG_V1_POLICY,
        PAPER_FORMULA_RAG_V1_POLICY,
    }


def build_retrieval_policy_from_env(
    env: Mapping[str, str] | None = None,
) -> RetrievalPolicy:
    values = env if env is not None else os.environ
    return build_retrieval_policy(values.get(NEWS_PAPER_RAG_POLICY_ENV))


@dataclass
class RetrievalRequest:
    paper_id: str
    question: str
    current_section_index: int = 0
    limit: int = 10


@dataclass
class RetrievalResult:
    parent_chunks: list[PaperChunk]       # section-level context for LLM
    child_chunks: list[PaperChunk]        # matched paragraph/proposition chunks
    ref_chunks: list[PaperChunk]          # cross-section reference expansions
    intent: QueryIntent
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_evidence_candidates(self) -> list[dict[str, Any]]:
        """Minimal dict representation for EvidenceCandidate construction."""
        out = []
        for chunk in _dedupe_chunks([*self.child_chunks, *self.ref_chunks, *self.parent_chunks]):
            source_ref = chunk.metadata.get("source_ref", f"arxiv://{chunk.paper_id}")
            out.append({
                "evidence_id": chunk.chunk_id,
                "title": chunk.section_title or chunk.chunk_type,
                "summary": chunk.content[:1200],
                "source_ref": source_ref,
                "span_refs": (chunk.chunk_id,),
                "evidence_type": chunk.chunk_type,
                "lineage": (chunk.paper_id,),
                "metadata": {
                    "section_role": chunk.section_role,
                    "section_index": chunk.section_index,
                    "has_formula": chunk.has_formula,
                    "has_figure": chunk.has_figure,
                    "intent": self.intent,
                    "expansion_reason": chunk.metadata.get("expansion_reason", ""),
                    "expanded_from_chunk_id": chunk.metadata.get("expanded_from_chunk_id", ""),
                    "expansion_edge": chunk.metadata.get("expansion_edge", ""),
                    "table_context_rerank_score": chunk.metadata.get("table_context_rerank_score"),
                    "table_context_rerank_strategy": chunk.metadata.get("table_context_rerank_strategy", ""),
                    "parent_expansion_reason": chunk.metadata.get("parent_expansion_reason", ""),
                    "parent_anchor_child_id": chunk.metadata.get("parent_anchor_child_id", ""),
                    "parent_snippet": chunk.metadata.get("parent_snippet", False),
                    "source_parent_chunk_id": chunk.metadata.get("source_parent_chunk_id", ""),
                    "parent_rerank_score": chunk.metadata.get("parent_rerank_score"),
                    "parent_rerank_strategy": chunk.metadata.get("parent_rerank_strategy", ""),
                    "parent_child_relevance_score": chunk.metadata.get("parent_child_relevance_score"),
                    "parent_relevance_score": chunk.metadata.get("parent_relevance_score"),
                    "parent_section_heading_score": chunk.metadata.get("parent_section_heading_score"),
                    "parent_position_score": chunk.metadata.get("parent_position_score"),
                    "parent_final_score": chunk.metadata.get("parent_final_score"),
                    "parent_score_strategy": chunk.metadata.get("parent_score_strategy", ""),
                    "parent_score_weights": chunk.metadata.get("parent_score_weights", {}),
                    "claim_index_hit": chunk.metadata.get("claim_index_hit", False),
                    "claim_index_score": chunk.metadata.get("claim_index_score"),
                    "claim_id": chunk.metadata.get("claim_id", ""),
                    "claim_text": chunk.metadata.get("claim_text", ""),
                    "claim_type": chunk.metadata.get("claim_type", ""),
                    "claim_source_locator": chunk.metadata.get("claim_source_locator", ""),
                    "title_score": chunk.metadata.get("title_score"),
                    "abstract_score": chunk.metadata.get("abstract_score"),
                    "caption_score": chunk.metadata.get("caption_score"),
                    "equation_score": chunk.metadata.get("equation_score"),
                    "body_score": chunk.metadata.get("body_score"),
                    "field_score": chunk.metadata.get("field_score"),
                    "field_score_weights": chunk.metadata.get("field_score_weights", {}),
                    "field_score_strategy": chunk.metadata.get("field_score_strategy", ""),
                    "title_embedding_score": chunk.metadata.get("title_embedding_score"),
                    "abstract_embedding_score": chunk.metadata.get("abstract_embedding_score"),
                    "caption_embedding_score": chunk.metadata.get("caption_embedding_score"),
                    "equation_embedding_score": chunk.metadata.get("equation_embedding_score"),
                    "body_embedding_score": chunk.metadata.get("body_embedding_score"),
                    "field_embedding_score": chunk.metadata.get("field_embedding_score"),
                    "field_embedding_scores": chunk.metadata.get("field_embedding_scores", {}),
                    "field_embedding_hits": chunk.metadata.get("field_embedding_hits", []),
                    "best_embedding_field": chunk.metadata.get("best_embedding_field", ""),
                    "field_embedding_strategy": chunk.metadata.get("field_embedding_strategy", ""),
                    "field_rerank_score": chunk.metadata.get("field_rerank_score"),
                    "field_rerank_strategy": chunk.metadata.get("field_rerank_strategy", ""),
                    "best_matching_field": chunk.metadata.get("best_matching_field", ""),
                    "element_label_score": chunk.metadata.get("element_label_score"),
                    "element_label_match": chunk.metadata.get("element_label_match", False),
                    "formula_symbol_score": chunk.metadata.get("formula_symbol_score"),
                    "formula_operator_score": chunk.metadata.get("formula_operator_score"),
                    "formula_label_score": chunk.metadata.get("formula_label_score"),
                    "formula_structure_score": chunk.metadata.get("formula_structure_score"),
                    "formula_context_score": chunk.metadata.get("formula_context_score"),
                    "formula_sparse_score": chunk.metadata.get("formula_sparse_score"),
                    "formula_sparse_boost": chunk.metadata.get("formula_sparse_boost"),
                    "formula_sparse_strategy": chunk.metadata.get("formula_sparse_strategy", ""),
                    "graph_score": chunk.metadata.get("graph_score"),
                    "child_score_strategy": chunk.metadata.get("child_score_strategy", ""),
                    "child_score_components": chunk.metadata.get("child_score_components", {}),
                    "field_text_available_fields": chunk.metadata.get("field_text_available_fields", ()),
                    "field_text_sources": chunk.metadata.get("field_text_sources", {}),
                    "content_span_unit": chunk.metadata.get("content_span_unit", ""),
                    "main_span": chunk.metadata.get("main_span", {}),
                    "overlap_spans": chunk.metadata.get("overlap_spans", []),
                    "child_semantic_score": chunk.metadata.get("child_semantic_score"),
                    "child_position_score": chunk.metadata.get("child_position_score"),
                    "child_final_score": chunk.metadata.get("child_final_score"),
                    "child_score_weights": chunk.metadata.get("child_score_weights", {}),
                },
            })
        return out


class ResearchRetriever:
    """
    Agent-callable retrieval tool.

    Flow: intent classification -> vector search (limit*3) ->
          position-aware re-rank -> parent expansion -> cross-ref expansion
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
        self._pipeline = RetrievalPipeline(
            policy=self._policy,
            planner=planner,
            recall_stage=self._recall_stage,
            rerank_cascade=rerank_cascade,
            child_scorer=child_scorer,
            visual_channel=self._visual_channel,
            parent_expander=parent_expander,
            cross_ref_expander=cross_ref_expander,
            table_context_expander=table_context_expander,
            structural_expander=structural_expander,
            supplemental_table_expander=supplemental_table_expander,
            request_factory=RetrievalRequest,
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


def _dedupe_chunks(chunks: list[PaperChunk]) -> list[PaperChunk]:
    return dedupe_by_key(chunks, key=lambda chunk: chunk.chunk_id)


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
