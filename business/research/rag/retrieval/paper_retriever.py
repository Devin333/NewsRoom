from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Mapping, TYPE_CHECKING

from framework.rag.core import intent_allowed, intent_budget, position_decay_score
from framework.rag.retrieval import dedupe_by_key

from business.research.document.models import PaperChunk
from business.research.ports.chunk_store import ChunkStorePort
from business.research.ports.field_embedding_index import FieldEmbeddingHit, FieldEmbeddingSearchPort
from business.research.ports.visual_chunk_index import VisualChunkHit, VisualChunkSearchPort
from business.research.rag.adapters.paper_field_text import FIELD_NAMES
from business.research.rag.retrieval.channels.claim_index import ClaimIndexChannel
from business.research.rag.retrieval.channels.dense_text import DenseTextChannel
from business.research.rag.retrieval.channels.field_embedding import FieldEmbeddingChannel
from business.research.rag.retrieval.channels.sparse_lexical import (
    SparseLexicalChannel,
    sparse_query_tokens,
)
from business.research.rag.retrieval.channels.visual import VisualRecallChannel
from business.research.rag.retrieval.expanders.cross_ref import CrossRefContextExpander
from business.research.rag.retrieval.expanders.formula_context import FormulaContextExpander
from business.research.rag.retrieval.expanders.parent import ParentContextExpander
from business.research.rag.retrieval.expanders.structural import StructuralContextExpander
from business.research.rag.retrieval.expanders.supplemental_table import SupplementalTableHitExpander
from business.research.rag.retrieval.expanders.table_context import TableContextExpander
from business.research.rag.retrieval.paper_claim_index import ClaimSearchHit, PaperClaimSearchPort
from business.research.rag.retrieval.fusion import fuse_chunk_rankings
from business.research.rag.retrieval.paper_policy import QueryIntent, RetrievalRoute
from business.research.rag.retrieval.paper_visual_retrieval import (
    PaperVisualFusionWeights,
    with_retrieval_scores,
)
from business.research.rag.retrieval.planner import QueryPlanner
from business.research.rag.retrieval.policy_config import policy_config_hash
from business.research.rag.retrieval.rerank import RerankCascade
from business.research.rag.retrieval.scoring import (
    ChildCandidateScorer,
    claim_from_citation_question,
    normalized_child_fallback_score_weights,
    normalized_child_final_score_weights,
    normalized_field_score_weights,
    normalized_parent_score_weights,
    round_score,
)
from business.research.rag.retrieval.trace import RetrievalDegradation, RetrievalTrace

if TYPE_CHECKING:
    from business.research.ports.reranker import RerankerPort

# Default position weight α per intent (0 = no position bias)
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
_HYBRID_RRF_INTENTS = (*HIGH_VALUE_VISUAL_RESULT_INTENTS, "formula_query", "citation_query")
_FORMULA_CONTEXT_REASONS = frozenset({
    "formula_nearby_context",
    "formula_explained_by",
    "formula_body_reference",
    "formula_explicit_reference",
    "formula_parent_context",
    "formula_reverse_context",
    "formula_reverse_reference",
})
@dataclass(frozen=True)
class RetrievalPolicy:
    """Tunable retrieval parameters (position weighting + over-fetch + rerank filter)."""
    name: str = DEFAULT_RETRIEVAL_POLICY
    position_alpha: dict[str, float] = field(default_factory=lambda: dict(_DEFAULT_ALPHA))
    default_alpha: float = 0.2          # fallback α for unlisted intents
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

    Flow: intent classification → vector search (limit*3) →
          position-aware re-rank → parent expansion → cross-ref expansion
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
        self._planner = QueryPlanner(self._policy)
        self._rerank_cascade = RerankCascade(
            self._policy,
            reranker=reranker,
            field_reranker=field_reranker,
        )
        self._parent_expander = ParentContextExpander(
            chunk_store,
            self._policy,
            reranker=reranker,
        )
        self._cross_ref_expander = CrossRefContextExpander(chunk_store)
        self._table_context_expander = TableContextExpander(
            chunk_store,
            self._policy,
            reranker=reranker,
        )
        self._formula_context_expander = FormulaContextExpander(self._policy)
        self._structural_expander = StructuralContextExpander(chunk_store, self._policy)
        self._supplemental_table_expander = SupplementalTableHitExpander(chunk_store, self._policy)
        self._child_scorer = ChildCandidateScorer(self._policy)
        self._reranker = reranker
        self._field_index = field_index
        self._field_reranker = field_reranker
        self._visual_store = visual_store
        self._claim_index = claim_index

    @property
    def policy(self) -> RetrievalPolicy:
        return self._policy

    def get_chunk(self, chunk_id: str) -> PaperChunk | None:
        """Expose deterministic chunk lookup for context assembly helpers."""
        return self._store.get_chunk(chunk_id)

    def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        import time
        t0 = time.perf_counter()
        plan = self._planner.build(request)
        route = plan.route
        candidate_filters = [dict(item) for item in plan.candidate_filters]
        active_policy_hash = policy_config_hash(self._policy)
        retrieval_trace = RetrievalTrace(
            policy_name=self._policy.name,
            policy_hash=active_policy_hash,
            route=plan.route_dict(),
        )

        # ── 1. vector search (over-fetch for re-ranking) ──────────────────────
        element_query_labels = set(plan.element_query_labels)
        candidate_limit = plan.candidate_limit
        candidates = self._search_text_candidates(
            request,
            route,
            candidate_filters,
            candidate_limit,
            trace=retrieval_trace,
        )
        n_recalled = len(candidates)
        field_hits = self._search_field_candidates(request, route, candidate_filters)
        candidates = self._merge_field_hits(candidates, field_hits, request.paper_id)
        claim_hits = self._search_claim_candidates(request, route, limit=candidate_limit)
        candidates = self._merge_claim_hits(candidates, claim_hits, request.paper_id)
        visual_hits = self._search_visual_candidates(request, route, candidate_filters)
        n_visual_recalled = len(visual_hits)
        if self._policy.hybrid_rrf_enabled and intent_allowed(route.intent, _HYBRID_RRF_INTENTS):
            candidates = self._fuse_hybrid_candidate_channels(
                candidates,
                field_hits=field_hits,
                claim_hits=claim_hits,
                visual_hits=visual_hits,
                paper_id=request.paper_id,
                limit=candidate_limit,
            )

        # ── 2. base relevance: reranker (if available) else vector score ──────
        base_reranker_enabled = self._rerank_cascade.base_enabled_for(route.intent)
        field_reranker_enabled = self._rerank_cascade.field_enabled_for(route.intent)
        base_scores = self._rerank_cascade.base_scores(request.question, candidates, intent=route.intent)

        # ── 2b. rerank score threshold: drop low-relevance candidates (reranker only) ──
        pairs = list(zip(candidates, base_scores))
        n_before_filter = len(pairs)
        if base_reranker_enabled and self._policy.rerank_score_threshold > 0.0:
            kept = [(c, b) for (c, b) in pairs if b >= self._policy.rerank_score_threshold]
            pairs = kept or pairs[:1]  # never drop everything — keep top-1 as fallback
        n_filtered = n_before_filter - len(pairs)
        field_rerank_scores = self._rerank_cascade.field_scores(
            request.question,
            [chunk for (chunk, _sem), _base in pairs],
            intent=route.intent,
        )

        # ── 3. position-aware re-rank ─────────────────────────────────────────
        scored = []
        for (chunk, _sem), base in pairs:
            retrieved = with_retrieval_scores(
                chunk,
                text_score=base,
                visual_score=None,
                fused_score=base,
                strategy="text",
            )
            scored.append(self._score_child_candidate(
                retrieved,
                request,
                route,
                semantic_score=base,
                field_rerank_score=field_rerank_scores.get(chunk.chunk_id),
            ))
        if visual_hits:
            scored = self._fuse_visual_scores(
                scored,
                visual_hits,
                paper_id=request.paper_id,
                query_text=request.question,
                current_section_index=request.current_section_index,
                intent=route.intent,
                field_rerank_scores=field_rerank_scores,
            )
        scored.sort(key=lambda x: x[1], reverse=True)
        child_chunks = [c for c, _ in scored[: request.limit]]
        child_chunks = self._interleave_structural_context(child_chunks, request, route)
        supplemental_table_chunks = self._supplemental_table_hits(child_chunks, request, route)
        child_chunks.extend(supplemental_table_chunks)
        top_score = scored[0][1] if scored else 0.0

        # ── 3. parent expansion ───────────────────────────────────────────────
        parent_chunks, parent_metrics = self._fetch_parents(child_chunks, request, route)

        # ── 4. cross-reference expansion ──────────────────────────────────────
        cross_ref_chunks = self._fetch_refs(child_chunks, request.paper_id)
        table_context_chunks = self._fetch_table_context(child_chunks, request, route)
        ref_chunks = _dedupe_chunks([*cross_ref_chunks, *table_context_chunks])

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        metrics = {
            "retrieval_policy": self._policy.name,
            "retrieval_policy_version": 1,
            "retrieval_policy_config_hash": active_policy_hash,
            "retrieval_policy_overfetch_multiplier": self._policy.overfetch_multiplier,
            "retrieval_policy_element_label_overfetch_multiplier": (
                self._policy.element_label_overfetch_multiplier
            ),
            "candidate_limit": candidate_limit,
            "candidate_filters": candidate_filters,
            "candidate_filter_group_count": len(candidate_filters),
            "hybrid_rrf_enabled": self._policy.hybrid_rrf_enabled,
            "multi_query_enabled": self._policy.multi_query_enabled,
            "sparse_lexical_enabled": self._policy.sparse_lexical_enabled,
            "formula_sparse_enabled": self._policy.formula_sparse_enabled,
            "sparse_recalled": sum(
                1 for chunk, _score in candidates
                if chunk.metadata.get("sparse_lexical_hit")
            ),
            "formula_sparse_recalled": sum(
                1 for chunk, _score in candidates
                if chunk.metadata.get("formula_sparse_hit")
            ),
            "hybrid_rrf_recalled": sum(
                1 for chunk, _score in candidates
                if chunk.metadata.get("hybrid_rrf_fusion")
            ),
            "query_variants": _recall_queries_for_policy(request.question, route.intent, self._policy),
            "element_query_labels": sorted(element_query_labels),
            "retrieval_policy_visual_fusion_weights": {
                "text": self._policy.visual_fusion_text_weight,
                "visual": self._policy.visual_fusion_visual_weight,
            },
            "intent": route.intent,
            "recall_routes": list(route.recall_routes),
            "route_plan": plan.route_dict(),
            "retrieval_plan": plan.to_dict(),
            "reranker": self._reranker is not None,
            "reranker_enabled_for_intent": base_reranker_enabled,
            "reranker_intent_scope": self._policy.reranking_intents,
            "recalled": n_recalled,
            "visual_recalled": n_visual_recalled,
            "visual_fusion_enabled": self._visual_store is not None,
            "field_embedding_enabled": self._field_index is not None and self._policy.field_embedding_enabled,
            "field_reranker_enabled": self._field_reranker is not None and self._policy.field_reranking_enabled,
            "field_reranker_enabled_for_intent": field_reranker_enabled,
            "field_reranker_intent_scope": self._policy.field_reranking_intents,
            "field_search_fields": self._policy.field_search_fields_for(route.intent),
            "field_hits_count": len(field_hits),
            "field_hits_by_name": _field_hits_by_name(field_hits),
            "claim_index_enabled": self._claim_index is not None,
            "claim_index_hits": len(claim_hits),
            "claim_index_top_claim_ids": [hit.record.claim_id for hit in claim_hits[:5]],
            "threshold_filtered": n_filtered,
            "child_returned": len(child_chunks),
            "parent_returned": len(parent_chunks),
            "ref_returned": len(ref_chunks),
            "supplemental_table_returned": len(supplemental_table_chunks),
            "table_context_returned": len(table_context_chunks),
            "figure_context_returned": sum(
                1 for chunk in child_chunks
                if chunk.metadata.get("expansion_reason") in {"figure_nearby_context", "figure_body_reference"}
            ),
            "formula_context_returned": sum(
                1 for chunk in child_chunks
                if chunk.metadata.get("expansion_reason") in _FORMULA_CONTEXT_REASONS
            ) + sum(
                1 for chunk in ref_chunks
                if chunk.metadata.get("expansion_reason") in _FORMULA_CONTEXT_REASONS
            ),
            "interleaved_table_context_returned": sum(
                1 for chunk in child_chunks
                if str(chunk.metadata.get("expansion_reason") or "").startswith("table_")
            ),
            "top_score": round(top_score, 4),
            "elapsed_ms": elapsed_ms,
            "field_scoring_enabled": self._policy.field_scoring_enabled,
            "field_score_weights": self._policy.field_score_weights_for(route.intent),
            "child_score_weights": self._policy.normalized_child_score_weights(),
            "field_scored_count": len(scored),
            "field_score_top": _metadata_extreme(scored, "field_score", max),
            "field_score_min": _metadata_extreme(scored, "field_score", min),
            "field_embedding_score_top": _metadata_extreme(scored, "field_embedding_score", max),
            "field_rerank_top": _metadata_extreme(scored, "field_rerank_score", max),
            "best_matching_fields": _best_matching_fields(scored),
            "retrieval_degradations": [item.to_dict() for item in retrieval_trace.degradations],
            "retrieval_trace": retrieval_trace.to_dict(),
        }
        metrics.update(parent_metrics)
        logging.getLogger(__name__).info("retrieval %s", metrics)

        return RetrievalResult(
            parent_chunks=parent_chunks,
            child_chunks=child_chunks,
            ref_chunks=ref_chunks,
            intent=route.intent,
            metadata=metrics,
        )

    # ── private ───────────────────────────────────────────────────────────────

    def _search_text_candidates(
        self,
        request: RetrievalRequest,
        route: RetrievalRoute,
        candidate_filters: list[dict[str, Any]],
        limit: int,
        *,
        trace: RetrievalTrace,
    ) -> list[tuple[PaperChunk, float]]:
        if self._policy.hybrid_rrf_enabled and intent_allowed(route.intent, _HYBRID_RRF_INTENTS):
            return self._search_hybrid_text_candidates(
                request,
                route,
                candidate_filters,
                limit,
                trace=trace,
            )
        by_id: dict[str, tuple[PaperChunk, float]] = {}
        query_texts = _recall_queries_for_policy(request.question, route.intent, self._policy)
        for filters in candidate_filters:
            for query_text in query_texts:
                for chunk, score in self._dense_channel.recall_chunks(
                    paper_id=request.paper_id,
                    query_text=query_text,
                    filters=filters,
                    limit=limit,
                ):
                    existing = by_id.get(chunk.chunk_id)
                    if existing is None or score > existing[1]:
                        by_id[chunk.chunk_id] = (chunk, score)
        candidates = list(by_id.values())
        candidates.sort(key=lambda item: item[1], reverse=True)
        return candidates[:limit]

    def _search_hybrid_text_candidates(
        self,
        request: RetrievalRequest,
        route: RetrievalRoute,
        candidate_filters: list[dict[str, Any]],
        limit: int,
        *,
        trace: RetrievalTrace,
    ) -> list[tuple[PaperChunk, float]]:
        rankings: list[tuple[str, list[tuple[PaperChunk, float]]]] = []
        query_texts = _recall_queries_for_policy(request.question, route.intent, self._policy)
        for filter_index, filters in enumerate(candidate_filters):
            for query_index, query_text in enumerate(query_texts):
                semantic_hits = self._dense_channel.recall_chunks(
                    paper_id=request.paper_id,
                    query_text=query_text,
                    filters=filters,
                    limit=limit,
                    suppress_errors=True,
                )
                if semantic_hits:
                    rankings.append((f"semantic:{filter_index}:{query_index}", semantic_hits))
                if self._policy.sparse_lexical_enabled:
                    sparse_limit = max(limit, request.limit * self._policy.sparse_search_limit_multiplier)
                    sparse_hits = self._sparse_lexical_candidates(
                        request.paper_id,
                        query_text,
                        filters=filters,
                        limit=sparse_limit,
                        formula_sparse_enabled=(
                            self._policy.formula_sparse_enabled and route.intent == "formula_query"
                        ),
                        trace=trace,
                    )
                    if sparse_hits:
                        rankings.append((f"sparse:{filter_index}:{query_index}", sparse_hits))
        return _rrf_fuse_rankings(
            rankings,
            limit=limit,
            rrf_k=self._policy.rrf_k,
            metadata_prefix="text",
        )

    def _sparse_lexical_candidates(
        self,
        paper_id: str,
        query_text: str,
        *,
        filters: dict[str, Any],
        limit: int,
        formula_sparse_enabled: bool = False,
        trace: RetrievalTrace | None = None,
    ) -> list[tuple[PaperChunk, float]]:
        return self._sparse_channel.recall_chunks(
            paper_id=paper_id,
            query_text=query_text,
            filters=filters,
            limit=limit,
            formula_sparse_enabled=formula_sparse_enabled,
            trace=trace,
        )

    def _search_field_candidates(
        self,
        request: RetrievalRequest,
        route: RetrievalRoute,
        candidate_filters: list[dict[str, Any]],
    ) -> list[FieldEmbeddingHit]:
        if self._field_index is None or not self._policy.field_embedding_enabled:
            return []
        limit = max(
            request.limit,
            request.limit
            * self._policy.overfetch_multiplier
            * max(1, self._policy.field_embedding_search_limit_multiplier),
        )
        return self._field_channel.search_hits(
            paper_id=request.paper_id,
            query_text=request.question,
            field_names=self._policy.field_search_fields_for(route.intent),
            candidate_filters=candidate_filters,
            limit=limit,
        )

    def _merge_field_hits(
        self,
        candidates: list[tuple[PaperChunk, float]],
        field_hits: list[FieldEmbeddingHit],
        paper_id: str,
    ) -> list[tuple[PaperChunk, float]]:
        return self._field_channel.merge_hits(candidates, field_hits, paper_id)

    def _search_claim_candidates(
        self,
        request: RetrievalRequest,
        route: RetrievalRoute,
        *,
        limit: int,
    ) -> list[ClaimSearchHit]:
        if self._claim_index is None or route.intent != "citation_query":
            return []
        return self._claim_channel.search_hits(
            paper_id=request.paper_id,
            query_text=request.question,
            limit=limit,
        )

    def _merge_claim_hits(
        self,
        candidates: list[tuple[PaperChunk, float]],
        claim_hits: list[ClaimSearchHit],
        paper_id: str,
    ) -> list[tuple[PaperChunk, float]]:
        return self._claim_channel.merge_hits(candidates, claim_hits, paper_id)

    def _fuse_hybrid_candidate_channels(
        self,
        candidates: list[tuple[PaperChunk, float]],
        *,
        field_hits: list[FieldEmbeddingHit],
        claim_hits: list[ClaimSearchHit],
        visual_hits: list[VisualChunkHit],
        paper_id: str,
        limit: int,
    ) -> list[tuple[PaperChunk, float]]:
        rankings: list[tuple[str, list[tuple[PaperChunk, float]]]] = []
        if candidates:
            ranked_candidates = sorted(candidates, key=lambda item: item[1], reverse=True)
            rankings.append(("text_sparse", ranked_candidates))
        field_ranked = self._field_hit_ranking(field_hits, paper_id)
        if field_ranked:
            rankings.append(("field_embedding", field_ranked))
        claim_ranked = self._claim_hit_ranking(claim_hits, paper_id)
        if claim_ranked:
            rankings.append(("claim", claim_ranked))
        visual_ranked = self._visual_hit_ranking(visual_hits, paper_id)
        if visual_ranked:
            rankings.append(("visual", visual_ranked))
        if len(rankings) <= 1:
            return candidates
        return _rrf_fuse_rankings(
            rankings,
            limit=limit,
            rrf_k=self._policy.rrf_k,
            metadata_prefix="hybrid",
        )

    def _field_hit_ranking(
        self,
        field_hits: list[FieldEmbeddingHit],
        paper_id: str,
    ) -> list[tuple[PaperChunk, float]]:
        return self._field_channel.ranked_chunks(field_hits, paper_id)

    def _claim_hit_ranking(
        self,
        claim_hits: list[ClaimSearchHit],
        paper_id: str,
    ) -> list[tuple[PaperChunk, float]]:
        return self._claim_channel.ranked_chunks(claim_hits, paper_id)

    def _visual_hit_ranking(
        self,
        visual_hits: list[VisualChunkHit],
        paper_id: str,
    ) -> list[tuple[PaperChunk, float]]:
        return self._visual_channel.ranked_chunks(visual_hits, paper_id)

    def _score_child_candidate(
        self,
        chunk: PaperChunk,
        request: RetrievalRequest,
        route: RetrievalRoute,
        *,
        semantic_score: float,
        field_rerank_score: float | None = None,
    ) -> tuple[PaperChunk, float]:
        return self._child_scorer.score(
            chunk,
            request,
            route,
            semantic_score=semantic_score,
            field_rerank_score=field_rerank_score,
        )

    def _search_visual_candidates(
        self,
        request: RetrievalRequest,
        route: RetrievalRoute,
        candidate_filters: list[dict[str, Any]],
    ) -> list[VisualChunkHit]:
        if self._visual_store is None or route.intent != "figure_query":
            return []
        limit = request.limit * self._policy.overfetch_multiplier
        return self._visual_channel.search_hits(
            paper_id=request.paper_id,
            query_text=request.question,
            candidate_filters=candidate_filters,
            limit=limit,
        )

    def _fuse_visual_scores(
        self,
        scored: list[tuple[PaperChunk, float]],
        visual_hits: list[VisualChunkHit],
        *,
        paper_id: str,
        query_text: str,
        current_section_index: int,
        intent: QueryIntent,
        field_rerank_scores: dict[str, float] | None = None,
    ) -> list[tuple[PaperChunk, float]]:
        fused: list[tuple[PaperChunk, float]] = []
        for fused_chunk, fused_score in self._visual_channel.fuse_scores(
            scored,
            visual_hits,
            paper_id=paper_id,
            weights=PaperVisualFusionWeights(
                text=self._policy.visual_fusion_text_weight,
                visual=self._policy.visual_fusion_visual_weight,
            ),
        ):
            fused.append(self._score_child_candidate(
                fused_chunk,
                RetrievalRequest(
                    paper_id=paper_id,
                    question=query_text,
                    current_section_index=current_section_index,
                ),
                RetrievalRoute(intent=intent),
                semantic_score=fused_score,
                field_rerank_score=(field_rerank_scores or {}).get(fused_chunk.chunk_id),
            ))
        return fused


    def _interleave_structural_context(
        self,
        chunks: list[PaperChunk],
        request: RetrievalRequest,
        route: RetrievalRoute,
    ) -> list[PaperChunk]:
        return self._structural_expander.expand(chunks, request, route)


    def _supplemental_table_hits(
        self,
        child_chunks: list[PaperChunk],
        request: RetrievalRequest,
        route: RetrievalRoute,
    ) -> list[PaperChunk]:
        return self._supplemental_table_expander.expand(child_chunks, request, route)

    def _fetch_table_context(
        self,
        chunks: list[PaperChunk],
        request: RetrievalRequest,
        route: RetrievalRoute,
    ) -> list[PaperChunk]:
        return self._table_context_expander.expand(chunks, request, route)

    def _fetch_parents(
        self,
        children: list[PaperChunk],
        request: RetrievalRequest,
        route: RetrievalRoute,
    ) -> tuple[list[PaperChunk], dict[str, Any]]:
        return self._parent_expander.expand(children, request, route)

    def _fetch_refs(
        self, children: list[PaperChunk], paper_id: str
    ) -> list[PaperChunk]:
        return self._cross_ref_expander.expand(children, paper_id)


def _metadata_float(metadata: dict[str, Any], key: str, default: float) -> float:
    value = metadata.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _metadata_extreme(
    scored: list[tuple[PaperChunk, float]],
    key: str,
    reducer: Any,
) -> float | None:
    values = [
        _metadata_float(chunk.metadata, key, 0.0)
        for chunk, _score in scored
        if key in chunk.metadata
    ]
    if not values:
        return None
    return round_score(reducer(values))


def _field_hits_by_name(hits: list[FieldEmbeddingHit]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for hit in hits:
        counts[hit.field_name] = counts.get(hit.field_name, 0) + 1
    return counts


def _best_matching_fields(scored: list[tuple[PaperChunk, float]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for chunk, _score in scored:
        field_name = str(chunk.metadata.get("best_matching_field") or "")
        if not field_name:
            continue
        counts[field_name] = counts.get(field_name, 0) + 1
    return counts


def _text_recall_queries(question: str, intent: str) -> list[str]:
    queries = [str(question or "")]
    if intent == "citation_query":
        claim = claim_from_citation_question(question)
        if claim:
            queries.append(claim)
    return _unique_nonempty_texts(queries)


def _recall_queries_for_policy(question: str, intent: str, policy: RetrievalPolicy) -> list[str]:
    queries = _text_recall_queries(question, intent)
    if not policy.multi_query_enabled:
        return queries
    sparse_terms = " ".join(sparse_query_tokens(question))
    if sparse_terms:
        queries.append(sparse_terms)
    intent_suffixes = {
        "figure_query": "figure caption visual description referenced paragraph",
        "table_query": "table caption rows columns result paragraph",
        "formula_query": "equation formula latex symbols explanation",
        "numerical_result": "experiment results table conclusion analysis",
        "comparison": "comparison baseline versus table result",
        "citation_query": "supporting evidence claim grounded passage",
        "contribution": "abstract contribution method novelty",
    }
    suffix = intent_suffixes.get(intent, "")
    if suffix and sparse_terms:
        queries.append(f"{sparse_terms} {suffix}")
    elif suffix:
        queries.append(f"{question} {suffix}")
    return _unique_nonempty_texts(queries)


def _rrf_fuse_rankings(
    rankings: list[tuple[str, list[tuple[PaperChunk, float]]]],
    *,
    limit: int,
    rrf_k: int,
    metadata_prefix: str,
) -> list[tuple[PaperChunk, float]]:
    return fuse_chunk_rankings(
        rankings,
        limit=limit,
        rrf_k=rrf_k,
        metadata_prefix=metadata_prefix,
    )


def _merge_chunk_metadata(base: PaperChunk, incoming: PaperChunk) -> PaperChunk:
    if base.chunk_id != incoming.chunk_id:
        return base
    metadata = dict(base.metadata)
    metadata.update(incoming.metadata)
    return base.model_copy(update={"metadata": metadata})


def _append_degradation_once(
    trace: RetrievalTrace,
    *,
    code: str,
    stage: str,
    paper_id: str,
    reason: str,
) -> None:
    trace.append_degradation_once(RetrievalDegradation(
        code=code,
        stage=stage,
        paper_id=paper_id,
        reason=reason,
    ))


def _unique_nonempty_texts(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


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
