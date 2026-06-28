from __future__ import annotations

import logging
import math
import os
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, TYPE_CHECKING

from framework.rag.core import intent_allowed, intent_budget, position_decay_score
from framework.rag.retrieval import (
    dedupe_by_key,
    expansion_metadata,
    normalize_score_weights,
    RerankScoreSet,
    rerank_sort_key,
    weighted_component_score,
)

from business.research.document.models import PaperChunk
from business.research.ports.chunk_store import ChunkStorePort
from business.research.ports.field_embedding_index import FieldEmbeddingHit, FieldEmbeddingSearchPort
from business.research.ports.visual_chunk_index import VisualChunkHit, VisualChunkSearchPort
from business.research.rag.adapters.paper_field_text import FIELD_NAMES, extract_field_texts
from business.research.rag.retrieval.paper_policy import QueryIntent, RetrievalRoute, build_retrieval_route
from business.research.rag.retrieval.paper_visual_retrieval import (
    PaperVisualFusionWeights,
    fuse_visual_retrieval_scores,
    with_retrieval_scores,
)

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

_TABLE_EXPANSION_INTENTS = frozenset({"table_query", "numerical_result", "comparison"})
_RESULT_SECTION_ROLES = frozenset({"experiment", "analysis", "conclusion"})
_RESULT_CONTEXT_KEYWORDS = (
    "sample quality",
    "result",
    "results",
    "experiment",
    "experiments",
    "evaluation",
    "ablation",
    "analysis",
    "conclusion",
    "benchmark",
    "quality",
    "accuracy",
    "fid",
    "inception score",
    "likelihood",
    "codelength",
    "bits/dim",
    "score",
)
_RESULT_QUESTION_KEYWORDS = (
    "result",
    "results",
    "experiment",
    "experiments",
    "accuracy",
    "f1",
    "score",
    "ablation",
    "\u5b9e\u9a8c\u7ed3\u679c",
    "\u7ed3\u679c",
    "\u8868\u660e",
)
_PARENT_SCORE_KEYS = ("child", "parent", "heading", "position")
_FIELD_SCORE_KEYS = FIELD_NAMES
_CHILD_FALLBACK_SCORE_KEYS = ("semantic", "field", "position", "graph")
_CHILD_FINAL_SCORE_KEYS = ("semantic", "field_embedding", "field_rerank", "position", "graph")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")
DEFAULT_RETRIEVAL_POLICY = "default"
PAPER_VISUAL_RAG_TUNED_POLICY = "paper_visual_rag_tuned"
NEWS_PAPER_RAG_POLICY_ENV = "NEWS_PAPER_RAG_POLICY"
HIGH_VALUE_VISUAL_RESULT_INTENTS = ("figure_query", "table_query", "numerical_result", "comparison")


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
    field_embedding_search_limit_multiplier: int = 2
    field_default_search_fields: tuple[str, ...] = ("title", "abstract", "caption", "equation", "body")
    field_intent_search_fields: dict[str, tuple[str, ...]] = field(default_factory=lambda: {
        "concept_method": ("title", "body"),
        "citation_query": ("body", "abstract", "title"),
        "contribution": ("abstract", "title", "body"),
        "figure_query": ("caption", "body"),
        "table_query": ("caption", "body"),
        "formula_query": ("equation", "body"),
        "numerical_result": ("caption", "body", "title"),
        "comparison": ("caption", "body", "title"),
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
        return _normalized_parent_score_weights(weights)

    def field_score_weights_for(self, intent: str) -> dict[str, float]:
        weights = dict(self.field_default_score_weights)
        weights.update(self.field_intent_score_weights.get(intent, {}))
        return _normalized_field_score_weights(weights)

    def normalized_child_score_weights(self) -> dict[str, float]:
        return _normalized_child_fallback_score_weights(self.child_score_weights)

    def normalized_child_final_score_weights(self) -> dict[str, float]:
        return _normalized_child_final_score_weights(self.child_final_score_weights)

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
    if normalized != PAPER_VISUAL_RAG_TUNED_POLICY:
        raise ValueError(
            f"unknown retrieval policy {policy_name!r}; expected "
            f"{DEFAULT_RETRIEVAL_POLICY!r} or {PAPER_VISUAL_RAG_TUNED_POLICY!r}"
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
    return RetrievalPolicy(
        name=PAPER_VISUAL_RAG_TUNED_POLICY,
        overfetch_multiplier=5,
        visual_fusion_text_weight=0.85,
        visual_fusion_visual_weight=0.15,
        reranking_intents=HIGH_VALUE_VISUAL_RESULT_INTENTS,
        field_reranking_intents=HIGH_VALUE_VISUAL_RESULT_INTENTS,
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
        field_intent_score_weights=field_intent_score_weights,
    )


def build_retrieval_policy_from_env(
    env: Mapping[str, str] | None = None,
) -> RetrievalPolicy:
    values = env if env is not None else os.environ
    return build_retrieval_policy(values.get(NEWS_PAPER_RAG_POLICY_ENV))


@dataclass(frozen=True)
class _ParentCandidate:
    parent: PaperChunk
    child: PaperChunk
    child_rank: int
    child_relevance_score: float = 0.0
    parent_relevance_score: float = 0.0
    section_heading_score: float = 0.0
    position_score: float = 0.0
    final_score: float = 0.0
    score_strategy: str = "deterministic"
    score_weights: dict[str, float] = field(default_factory=dict)
    rerank_score: float | None = None
    rerank_query: str = ""


@dataclass(frozen=True)
class _FieldScores:
    title_score: float
    abstract_score: float
    caption_score: float
    equation_score: float
    body_score: float
    field_score: float
    weights: dict[str, float]
    strategy: str = "lexical_overlap"


@dataclass(frozen=True)
class _FieldEmbeddingSummary:
    scores: dict[str, float]
    best_field: str = ""
    best_score: float = 0.0
    hits: tuple[dict[str, Any], ...] = ()


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
    ) -> None:
        self._store = chunk_store
        self._policy = policy or RetrievalPolicy()
        self._reranker = reranker
        self._field_index = field_index
        self._field_reranker = field_reranker
        self._visual_store = visual_store

    @property
    def policy(self) -> RetrievalPolicy:
        return self._policy

    def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        import time
        t0 = time.perf_counter()
        route = build_retrieval_route(request.question)
        filters = self._build_filters(route)
        candidate_filters = self._candidate_filters(route, filters)

        # ── 1. vector search (over-fetch for re-ranking) ──────────────────────
        element_query_labels = _element_query_labels(request.question, route.intent)
        candidate_limit = request.limit * self._policy.overfetch_multiplier
        if element_query_labels:
            candidate_limit = max(
                candidate_limit,
                request.limit * self._policy.element_label_overfetch_multiplier,
            )
        if route.intent == "citation_query":
            candidate_limit = max(
                candidate_limit,
                request.limit * self._policy.citation_claim_overfetch_multiplier,
            )
        candidates = self._search_text_candidates(request, route, candidate_filters, candidate_limit)
        n_recalled = len(candidates)
        field_hits = self._search_field_candidates(request, route, candidate_filters)
        candidates = self._merge_field_hits(candidates, field_hits, request.paper_id)
        visual_hits = self._search_visual_candidates(request, route, candidate_filters)
        n_visual_recalled = len(visual_hits)

        # ── 2. base relevance: reranker (if available) else vector score ──────
        base_reranker_enabled = self._base_reranker_enabled(route.intent)
        field_reranker_enabled = self._field_reranker_enabled(route.intent)
        base_scores = self._base_scores(request.question, candidates, intent=route.intent)

        # ── 2b. rerank score threshold: drop low-relevance candidates (reranker only) ──
        pairs = list(zip(candidates, base_scores))
        n_before_filter = len(pairs)
        if base_reranker_enabled and self._policy.rerank_score_threshold > 0.0:
            kept = [(c, b) for (c, b) in pairs if b >= self._policy.rerank_score_threshold]
            pairs = kept or pairs[:1]  # never drop everything — keep top-1 as fallback
        n_filtered = n_before_filter - len(pairs)
        field_rerank_scores = self._field_rerank_scores(
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
            "retrieval_policy_overfetch_multiplier": self._policy.overfetch_multiplier,
            "retrieval_policy_element_label_overfetch_multiplier": (
                self._policy.element_label_overfetch_multiplier
            ),
            "candidate_limit": candidate_limit,
            "candidate_filters": candidate_filters,
            "candidate_filter_group_count": len(candidate_filters),
            "element_query_labels": sorted(element_query_labels),
            "retrieval_policy_visual_fusion_weights": {
                "text": self._policy.visual_fusion_text_weight,
                "visual": self._policy.visual_fusion_visual_weight,
            },
            "intent": route.intent,
            "recall_routes": list(route.recall_routes),
            "route_plan": {
                "primary_intent": route.intent,
                "recall_routes": list(route.recall_routes),
                "candidate_filters": candidate_filters,
            },
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
                if chunk.metadata.get("expansion_reason") in {"formula_parent_context", "formula_body_reference"}
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

    def _base_scores(
        self,
        question: str,
        candidates: list[tuple[PaperChunk, float]],
        *,
        intent: str,
    ) -> list[float]:
        """Base relevance per candidate: reranker cross-encoder score if available,
        else the vector semantic score. Reranker scores replace (not add to) vector
        scores since the cross-encoder is a stronger relevance signal."""
        if self._reranker is None or not candidates or not self._policy.reranker_enabled_for(intent):
            return [sem for _chunk, sem in candidates]
        passages = [chunk.content for chunk, _ in candidates]
        try:
            scores = self._reranker.score(question, passages)
        except Exception:
            import logging
            logging.getLogger(__name__).warning("reranker failed, falling back to vector scores")
            return [sem for _chunk, sem in candidates]
        normalized_scores = RerankScoreSet.from_raw(scores, expected_count=len(candidates))
        if normalized_scores is None:
            logging.getLogger(__name__).warning(
                "reranker returned %s scores for %s candidates",
                len(scores),
                len(candidates),
            )
            return [sem for _chunk, sem in candidates]
        return list(normalized_scores.scores)

    def _build_filters(self, route: RetrievalRoute) -> dict[str, Any]:
        filters: dict[str, Any] = {}
        if route.extra_filters:
            filters.update(route.extra_filters)
        return filters

    def _candidate_filters(self, route: RetrievalRoute, base_filters: dict[str, Any]) -> list[dict[str, Any]]:
        if route.candidate_filter_groups:
            return _dedupe_filters([
                {**base_filters, **dict(filters)}
                for filters in route.candidate_filter_groups
            ])
        if "chunk_type" in base_filters or not route.chunk_type_filter:
            return [dict(base_filters)]
        return [
            {**base_filters, "chunk_type": chunk_type}
            for chunk_type in route.chunk_type_filter
        ]

    def _search_text_candidates(
        self,
        request: RetrievalRequest,
        route: RetrievalRoute,
        candidate_filters: list[dict[str, Any]],
        limit: int,
    ) -> list[tuple[PaperChunk, float]]:
        by_id: dict[str, tuple[PaperChunk, float]] = {}
        query_texts = _text_recall_queries(request.question, route.intent)
        for filters in candidate_filters:
            for query_text in query_texts:
                for chunk, score in self._store.search_with_scores(
                    request.paper_id,
                    query_text,
                    filters=filters,
                    limit=limit,
                ):
                    existing = by_id.get(chunk.chunk_id)
                    if existing is None or score > existing[1]:
                        by_id[chunk.chunk_id] = (chunk, score)
        candidates = list(by_id.values())
        candidates.sort(key=lambda item: item[1], reverse=True)
        return candidates[:limit]

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
        hits_by_key: dict[tuple[str, str], FieldEmbeddingHit] = {}
        for filters in candidate_filters:
            try:
                hits = self._field_index.search_field_vectors(
                    request.paper_id,
                    request.question,
                    field_names=self._policy.field_search_fields_for(route.intent),
                    filters=filters,
                    limit=limit,
                )
            except Exception:
                logging.getLogger(__name__).warning("field embedding retrieval failed", exc_info=True)
                return []
            for hit in hits:
                key = (hit.chunk_id, hit.field_name)
                existing = hits_by_key.get(key)
                if existing is None or hit.score > existing.score:
                    hits_by_key[key] = hit
        hits = list(hits_by_key.values())
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:limit]

    def _merge_field_hits(
        self,
        candidates: list[tuple[PaperChunk, float]],
        field_hits: list[FieldEmbeddingHit],
        paper_id: str,
    ) -> list[tuple[PaperChunk, float]]:
        if not field_hits:
            return candidates

        by_id: dict[str, tuple[PaperChunk, float]] = {
            chunk.chunk_id: (chunk, score)
            for chunk, score in candidates
        }
        for hit in field_hits:
            existing = by_id.get(hit.chunk_id)
            chunk = existing[0] if existing else self._store.get_chunk(hit.chunk_id)
            if chunk is None or chunk.paper_id != paper_id:
                continue
            metadata = _merge_field_embedding_hit(chunk.metadata, hit)
            merged_chunk = chunk.model_copy(update={"metadata": metadata})
            by_id[merged_chunk.chunk_id] = (merged_chunk, existing[1] if existing else 0.0)
        return list(by_id.values())

    def _base_reranker_enabled(self, intent: str) -> bool:
        return self._reranker is not None and self._policy.reranker_enabled_for(intent)

    def _field_reranker_enabled(self, intent: str) -> bool:
        return self._field_reranker is not None and self._policy.field_reranker_enabled_for(intent)

    def _field_rerank_scores(
        self,
        question: str,
        chunks: list[PaperChunk],
        *,
        intent: str,
    ) -> dict[str, float]:
        if (
            not self._field_reranker_enabled(intent)
            or not chunks
        ):
            return {}
        passages = [_field_rerank_passage(chunk) for chunk in chunks]
        try:
            scores = self._field_reranker.score(question, passages)
        except Exception:
            logging.getLogger(__name__).warning("field reranker failed", exc_info=True)
            return {}
        normalized_scores = RerankScoreSet.from_raw(scores, expected_count=len(chunks))
        if normalized_scores is None:
            logging.getLogger(__name__).warning(
                "field reranker returned %s scores for %s candidates",
                len(scores),
                len(chunks),
            )
            return {}
        return normalized_scores.as_id_map([chunk.chunk_id for chunk in chunks])

    def _score_child_candidate(
        self,
        chunk: PaperChunk,
        request: RetrievalRequest,
        route: RetrievalRoute,
        *,
        semantic_score: float,
        field_rerank_score: float | None = None,
    ) -> tuple[PaperChunk, float]:
        semantic = _clamp_score(semantic_score)
        position_score = _child_position_score(
            self._policy,
            route.intent,
            chunk.section_index,
            request.current_section_index,
        )
        field_scores = _field_scores_for_chunk(
            request.question,
            chunk,
            self._policy.field_score_weights_for(route.intent),
            enabled=self._policy.field_scoring_enabled,
        )
        field_summary = _field_embedding_summary_from_metadata(chunk.metadata)
        field_rerank = _clamp_score(field_rerank_score) if field_rerank_score is not None else 0.0
        graph_score = _child_graph_score(chunk)
        route_match_score = _route_match_score(route, chunk)
        element_label_score = _element_label_match_score(request.question, route.intent, chunk)
        graph_score = max(graph_score, element_label_score)
        element_label_boost = _clamp_score(
            element_label_score * max(0.0, self._policy.element_label_boosts.get(route.intent, 0.0))
        )
        citation_claim_score = _citation_claim_match_score(request.question, chunk)
        citation_claim_boost = _clamp_score(
            citation_claim_score * max(0.0, self._policy.citation_claim_boost)
        ) if route.intent == "citation_query" else 0.0
        has_field_semantic = field_summary.best_score > 0.0 or field_rerank_score is not None
        if has_field_semantic:
            child_weights = self._policy.normalized_child_final_score_weights()
            final_score = weighted_component_score(
                {
                    "semantic": semantic,
                    "field_embedding": field_summary.best_score,
                    "field_rerank": field_rerank,
                    "position": position_score,
                    "graph": graph_score,
                },
                child_weights,
            )
            score_strategy = "semantic_field_embedding_rerank_fusion"
        else:
            child_weights = self._policy.normalized_child_score_weights()
            final_score = weighted_component_score(
                {
                    "semantic": semantic,
                    "field": field_scores.field_score,
                    "position": position_score,
                    "graph": graph_score,
                },
                child_weights,
            )
            score_strategy = "semantic_lexical_field_fallback"
        final_score = _clamp_score(final_score + element_label_boost + citation_claim_boost)
        field_texts = extract_field_texts(chunk)
        best_matching_field = _best_matching_field(field_summary, field_scores)
        metadata = dict(chunk.metadata)
        metadata.update({
            "title_score": field_scores.title_score,
            "abstract_score": field_scores.abstract_score,
            "caption_score": field_scores.caption_score,
            "equation_score": field_scores.equation_score,
            "body_score": field_scores.body_score,
            "field_score": field_scores.field_score,
            "field_score_weights": dict(field_scores.weights),
            "field_score_strategy": field_scores.strategy,
            "title_embedding_score": field_summary.scores.get("title", 0.0),
            "abstract_embedding_score": field_summary.scores.get("abstract", 0.0),
            "caption_embedding_score": field_summary.scores.get("caption", 0.0),
            "equation_embedding_score": field_summary.scores.get("equation", 0.0),
            "body_embedding_score": field_summary.scores.get("body", 0.0),
            "field_embedding_score": _round_score(field_summary.best_score),
            "best_embedding_field": field_summary.best_field,
            "field_embedding_hits": list(field_summary.hits),
            "field_embedding_strategy": "field_vector_search" if field_summary.best_score > 0.0 else "",
            "field_rerank_score": _round_score(field_rerank) if field_rerank_score is not None else None,
            "field_rerank_strategy": "cross_encoder_structured_fields" if field_rerank_score is not None else "",
            "best_matching_field": best_matching_field,
            "element_label_score": _round_score(element_label_score),
            "element_label_match": element_label_score > 0.0,
            "element_label_boost": _round_score(element_label_boost),
            "citation_claim_score": _round_score(citation_claim_score),
            "citation_claim_boost": _round_score(citation_claim_boost),
            "graph_score": _round_score(graph_score),
            "route_match_score": _round_score(route_match_score),
            "matched_recall_routes": list(_matched_recall_routes(route, chunk)),
            "child_score_strategy": score_strategy,
            "child_score_components": {
                "semantic": _round_score(semantic),
                "deterministic_field": field_scores.field_score,
                "field_embedding": _round_score(field_summary.best_score),
                "field_rerank": _round_score(field_rerank) if field_rerank_score is not None else None,
                "position": _round_score(position_score),
                "graph": _round_score(graph_score),
                "route_match": _round_score(route_match_score),
                "element_label": _round_score(element_label_score),
                "element_label_boost": _round_score(element_label_boost),
                "citation_claim": _round_score(citation_claim_score),
                "citation_claim_boost": _round_score(citation_claim_boost),
            },
            "child_semantic_score": _round_score(semantic),
            "child_position_score": _round_score(position_score),
            "child_final_score": _round_score(final_score),
            "child_score_weights": dict(child_weights),
            "field_text_available_fields": field_texts.available_fields(),
            "field_text_sources": {
                field_name: field_texts.sources_for(field_name)
                for field_name in field_texts.available_fields()
            },
        })
        return chunk.model_copy(update={"metadata": metadata}), _round_score(final_score)

    def _search_visual_candidates(
        self,
        request: RetrievalRequest,
        route: RetrievalRoute,
        candidate_filters: list[dict[str, Any]],
    ) -> list[VisualChunkHit]:
        if self._visual_store is None or route.intent != "figure_query":
            return []
        limit = request.limit * self._policy.overfetch_multiplier
        hits_by_id: dict[str, VisualChunkHit] = {}
        for filters in candidate_filters:
            try:
                hits = self._visual_store.search_visual_chunks(
                    request.paper_id,
                    request.question,
                    filters=filters,
                    limit=limit,
                )
            except Exception:
                logging.getLogger(__name__).warning("visual retrieval failed", exc_info=True)
                return []
            for hit in hits:
                existing = hits_by_id.get(hit.chunk_id)
                if existing is None or hit.score > existing.score:
                    hits_by_id[hit.chunk_id] = hit
        hits = list(hits_by_id.values())
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:limit]

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
        for fused_chunk, fused_score in fuse_visual_retrieval_scores(
            scored,
            visual_hits,
            paper_id=paper_id,
            chunk_lookup=self._store,
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
        if not chunks:
            return chunks
        out: list[PaperChunk] = []
        seen: set[str] = set()
        for chunk in chunks:
            if chunk.chunk_id not in seen:
                out.append(chunk)
                seen.add(chunk.chunk_id)
            added = 0
            for ref_id, reason, edge in self._structural_context_refs(chunk, request, route):
                if ref_id in seen:
                    continue
                ref = self._store.get_chunk(ref_id)
                if ref is None or ref.paper_id != request.paper_id:
                    continue
                seen.add(ref.chunk_id)
                added += 1
                out.append(_with_expansion_metadata(
                    ref,
                    expanded_from_chunk_id=chunk.chunk_id,
                    reason=reason,
                    edge=edge,
                    rank=added,
                ))
        return out

    def _structural_context_refs(
        self,
        chunk: PaperChunk,
        request: RetrievalRequest,
        route: RetrievalRoute,
    ) -> list[tuple[str, str, str]]:
        if route.intent == "figure_query" and self._policy.max_figure_context_chunks > 0 and _is_figure_chunk(chunk):
            return _figure_context_refs(chunk)[: self._policy.max_figure_context_chunks]
        if _is_table_chunk(chunk) and _should_expand_result_context(route.intent, request.question):
            return _table_context_refs(chunk)[: self._policy.max_table_context_chunks]
        if (
            _is_formula_chunk(chunk)
            and self._policy.max_formula_context_chunks > 0
            and _should_expand_formula_context(route.intent, request.question)
        ):
            return _formula_context_refs(chunk)[: self._policy.max_formula_context_chunks]
        return []


    def _supplemental_table_hits(
        self,
        child_chunks: list[PaperChunk],
        request: RetrievalRequest,
        route: RetrievalRoute,
    ) -> list[PaperChunk]:
        if not _should_expand_result_context(route.intent, request.question):
            return []
        if any(_is_table_chunk(chunk) for chunk in child_chunks):
            return []
        seen = {chunk.chunk_id for chunk in child_chunks}
        try:
            candidates = self._store.search_with_scores(
                request.paper_id,
                request.question,
                filters={"chunk_type": "table"},
                limit=self._policy.supplemental_table_result_limit,
            )
        except Exception:
            logging.getLogger(__name__).warning("supplemental table retrieval failed", exc_info=True)
            return []
        out: list[PaperChunk] = []
        for chunk, score in candidates:
            if chunk.paper_id != request.paper_id or chunk.chunk_id in seen or not _is_table_chunk(chunk):
                continue
            seen.add(chunk.chunk_id)
            scored = with_retrieval_scores(
                chunk,
                text_score=score,
                visual_score=None,
                fused_score=score,
                strategy="supplemental_table_text",
            )
            scored, _final_score = self._score_child_candidate(
                scored,
                request,
                route,
                semantic_score=score,
            )
            metadata = dict(scored.metadata)
            metadata["supplemental_reason"] = "result_intent_table_search"
            out.append(scored.model_copy(update={"metadata": metadata}))
        return out

    def _fetch_table_context(
        self,
        chunks: list[PaperChunk],
        request: RetrievalRequest,
        route: RetrievalRoute,
    ) -> list[PaperChunk]:
        table_hits = [chunk for chunk in chunks if _is_table_chunk(chunk)]
        if not table_hits:
            return []

        seen = {chunk.chunk_id for chunk in chunks}
        out: list[PaperChunk] = []
        include_result_context = _should_expand_result_context(route.intent, request.question)

        for table in table_hits:
            added_for_table = 0
            expansion_rank = 0

            def add_chunk(chunk: PaperChunk | None, *, reason: str, edge: str) -> None:
                nonlocal added_for_table, expansion_rank
                if added_for_table >= self._policy.max_table_context_chunks:
                    return
                if chunk is None or chunk.paper_id != request.paper_id or chunk.chunk_id in seen:
                    return
                seen.add(chunk.chunk_id)
                added_for_table += 1
                expansion_rank += 1
                out.append(_with_expansion_metadata(
                    chunk,
                    expanded_from_chunk_id=table.chunk_id,
                    reason=reason,
                    edge=edge,
                    rank=expansion_rank,
                ))

            nearby_id = str(table.metadata.get("nearby_context_chunk_id") or "")
            add_chunk(
                self._store.get_chunk(nearby_id) if nearby_id else None,
                reason="table_nearby_context",
                edge="nearby_context_chunk_id",
            )

            for ref in table.metadata.get("referenced_by_chunks", []):
                if not isinstance(ref, dict):
                    continue
                ref_id = str(ref.get("chunk_id") or "")
                add_chunk(
                    self._store.get_chunk(ref_id) if ref_id else None,
                    reason="table_body_reference",
                    edge="referenced_by_chunks",
                )

            parent_table_id = str(table.metadata.get("parent_table_chunk_id") or "")
            add_chunk(
                self._store.get_chunk(parent_table_id) if parent_table_id else None,
                reason="table_row_group_parent",
                edge="parent_table_chunk_id",
            )

            parent_id = table.parent_chunk_id or ""
            add_chunk(
                self._store.get_chunk(parent_id) if parent_id else None,
                reason="table_parent_context",
                edge="parent_chunk_id",
            )

            if not include_result_context:
                continue
            remaining = self._policy.max_table_context_chunks - added_for_table
            if remaining <= 0:
                continue
            for chunk in self._result_context_candidates(table, request, seen, limit=remaining):
                add_chunk(
                    chunk,
                    reason="table_result_context",
                    edge="section_role_or_title",
                )

        return out

    def _result_context_candidates(
        self,
        table: PaperChunk,
        request: RetrievalRequest,
        seen: set[str],
        *,
        limit: int,
    ) -> list[PaperChunk]:
        if limit <= 0:
            return []
        query_text = f"{request.question}\n{table.section_title}\n{table.content[:1000]}"
        try:
            scored = self._store.search_with_scores(
                request.paper_id,
                query_text,
                filters={"chunk_type": "paragraph"},
                limit=self._policy.table_result_context_search_limit,
            )
        except Exception:
            logging.getLogger(__name__).warning("table result context retrieval failed", exc_info=True)
            return []

        candidates: list[tuple[tuple[int, int, int], float, PaperChunk]] = []
        for chunk, score in scored:
            if chunk.paper_id != request.paper_id or chunk.chunk_id in seen:
                continue
            priority = _result_context_priority(chunk, table)
            if priority is None:
                continue
            candidates.append((priority, score, chunk))
        if self._reranker is not None:
            reranked = self._rerank_table_result_context(table, request, candidates, limit=limit)
            if reranked:
                return reranked
        candidates.sort(key=lambda item: (*item[0], -item[1]))
        return [chunk for _priority, _score, chunk in candidates[:limit]]

    def _rerank_table_result_context(
        self,
        table: PaperChunk,
        request: RetrievalRequest,
        candidates: list[tuple[tuple[int, int, int], float, PaperChunk]],
        *,
        limit: int,
    ) -> list[PaperChunk]:
        if not candidates:
            return []
        query_text = _table_context_rerank_query(table, request)
        try:
            scores = self._reranker.score(  # type: ignore[union-attr]
                query_text,
                [chunk.content for _priority, _vector_score, chunk in candidates],
            )
        except Exception:
            logging.getLogger(__name__).warning("table context reranker failed", exc_info=True)
            return []
        normalized_scores = RerankScoreSet.from_raw(scores, expected_count=len(candidates))
        if normalized_scores is None:
            logging.getLogger(__name__).warning(
                "table context reranker returned %s scores for %s candidates",
                len(scores),
                len(candidates),
            )
            return []

        ranked: list[tuple[float, tuple[int, int, int], float, PaperChunk]] = []
        for rerank_score, (priority, vector_score, chunk) in zip(normalized_scores.scores, candidates, strict=True):
            if rerank_score < self._policy.table_context_rerank_score_threshold:
                continue
            metadata = dict(chunk.metadata)
            metadata.update({
                "table_context_rerank_score": round(rerank_score, 6),
                "table_context_rerank_strategy": "cross_encoder",
                "table_context_rerank_query": query_text[:400],
            })
            ranked.append((
                float(rerank_score),
                priority,
                vector_score,
                chunk.model_copy(update={"metadata": metadata}),
            ))
        ranked.sort(key=lambda item: rerank_sort_key(
            rerank_score=item[0],
            priority=item[1],
            fallback_score=item[2],
        ))
        return [chunk for _rerank, _priority, _vector_score, chunk in ranked[:limit]]

    def _fetch_parents(
        self,
        children: list[PaperChunk],
        request: RetrievalRequest,
        route: RetrievalRoute,
    ) -> tuple[list[PaperChunk], dict[str, Any]]:
        candidates = self._parent_candidates(children, request.paper_id)
        max_chunks, max_tokens = self._policy.parent_budget_for(route.intent)
        score_weights = self._policy.parent_score_weights_for(route.intent)
        metrics: dict[str, Any] = {
            "parent_budget_chunks": max_chunks,
            "parent_budget_tokens": max_tokens,
            "parent_tokens_used": 0,
            "parent_snippets_returned": 0,
            "parent_budget_exhausted": False,
            "parent_scoring_enabled": bool(candidates),
            "parent_score_weights": score_weights,
            "parent_candidates_scored": 0,
            "parent_score_top": None,
            "parent_score_min": None,
        }
        # fall back to children themselves if no parents found (e.g. abstract)
        if not candidates:
            return list(children), metrics
        if max_chunks <= 0 or max_tokens <= 0:
            metrics["parent_budget_exhausted"] = True
            return [], metrics

        ranked = self._rank_parent_candidates(candidates, request, route, score_weights)
        if ranked:
            final_scores = [candidate.final_score for candidate in ranked]
            metrics.update({
                "parent_candidates_scored": len(ranked),
                "parent_score_top": round(max(final_scores), 6),
                "parent_score_min": round(min(final_scores), 6),
            })
        parents: list[PaperChunk] = []
        tokens_used = 0
        snippets = 0
        exhausted = False

        for candidate in ranked:
            if len(parents) >= max_chunks:
                exhausted = True
                break
            remaining_tokens = max_tokens - tokens_used
            if remaining_tokens <= 0:
                exhausted = True
                break
            chunk = self._parent_context_chunk(
                candidate,
                rank=len(parents) + 1,
                token_window=min(self._policy.parent_snippet_token_window, remaining_tokens),
            )
            token_estimate = _estimate_tokens(chunk.content)
            if token_estimate > remaining_tokens:
                chunk = self._parent_context_chunk(
                    candidate,
                    rank=len(parents) + 1,
                    token_window=remaining_tokens,
                    force_snippet=True,
                )
                token_estimate = _estimate_tokens(chunk.content)
            if token_estimate <= 0:
                continue
            if token_estimate > remaining_tokens:
                exhausted = True
                continue
            parents.append(chunk)
            tokens_used += token_estimate
            if chunk.metadata.get("parent_snippet"):
                snippets += 1

        metrics.update({
            "parent_tokens_used": tokens_used,
            "parent_snippets_returned": snippets,
            "parent_budget_exhausted": exhausted,
        })
        return parents, metrics

    def _parent_candidates(self, children: list[PaperChunk], paper_id: str) -> list[_ParentCandidate]:
        seen: set[str] = set()
        candidates: list[_ParentCandidate] = []
        for child_rank, child in enumerate(children):
            parent_id = child.parent_chunk_id
            if not parent_id or parent_id in seen:
                continue
            parent = self._store.get_chunk(parent_id)
            if parent is None or parent.paper_id != paper_id:
                continue
            seen.add(parent.chunk_id)
            candidates.append(_ParentCandidate(
                parent=parent,
                child=child,
                child_rank=child_rank,
                child_relevance_score=_child_relevance_score(child, child_rank),
            ))
        return candidates

    def _rank_parent_candidates(
        self,
        candidates: list[_ParentCandidate],
        request: RetrievalRequest,
        route: RetrievalRoute,
        score_weights: dict[str, float],
    ) -> list[_ParentCandidate]:
        if not candidates:
            return []
        rerank_query = ""
        rerank_scores: list[float] | None = None
        if self._base_reranker_enabled(route.intent):
            rerank_query = _parent_context_rerank_query(request, route, candidates)
            passages = [_parent_context_rerank_passage(candidate) for candidate in candidates]
            try:
                scores = self._reranker.score(rerank_query, passages)  # type: ignore[union-attr]
                normalized_scores = RerankScoreSet.from_raw(scores, expected_count=len(candidates))
                if normalized_scores is None:
                    logging.getLogger(__name__).warning(
                        "parent context reranker returned %s scores for %s candidates",
                        len(scores),
                        len(candidates),
                    )
                else:
                    rerank_scores = list(normalized_scores.scores)
            except Exception:
                logging.getLogger(__name__).warning("parent context reranker failed", exc_info=True)

        ranked = [
            self._score_parent_candidate(
                candidate,
                request,
                route,
                score_weights,
                rerank_score=rerank_scores[index] if rerank_scores is not None else None,
                rerank_query=rerank_query if rerank_scores is not None else "",
            )
            for index, candidate in enumerate(candidates)
        ]
        ranked.sort(key=lambda candidate: (-candidate.final_score, candidate.child_rank, candidate.parent.chunk_id))
        threshold = self._policy.parent_rerank_score_threshold
        if threshold <= 0.0 or rerank_scores is None:
            return ranked
        filtered = [
            candidate for candidate in ranked
            if candidate.rerank_score is not None and candidate.rerank_score >= threshold
        ]
        return filtered or ranked[:1]

    def _score_parent_candidate(
        self,
        candidate: _ParentCandidate,
        request: RetrievalRequest,
        route: RetrievalRoute,
        score_weights: dict[str, float],
        *,
        rerank_score: float | None,
        rerank_query: str,
    ) -> _ParentCandidate:
        heading_score = _parent_section_heading_score(route.intent, candidate.parent)
        position_score = _parent_position_score(self._policy, route.intent, candidate.parent, request)
        parent_relevance_score = (
            _clamp_score(rerank_score)
            if rerank_score is not None
            else _deterministic_parent_relevance(candidate.child_relevance_score, heading_score)
        )
        final_score = weighted_component_score(
            {
                "child": candidate.child_relevance_score,
                "parent": parent_relevance_score,
                "heading": heading_score,
                "position": position_score,
            },
            score_weights,
        )
        return _ParentCandidate(
            parent=candidate.parent,
            child=candidate.child,
            child_rank=candidate.child_rank,
            child_relevance_score=_round_score(candidate.child_relevance_score),
            parent_relevance_score=_round_score(parent_relevance_score),
            section_heading_score=_round_score(heading_score),
            position_score=_round_score(position_score),
            final_score=_round_score(final_score),
            score_strategy="cross_encoder" if rerank_score is not None else "deterministic",
            score_weights=score_weights,
            rerank_score=rerank_score,
            rerank_query=rerank_query,
        )

    def _parent_context_chunk(
        self,
        candidate: _ParentCandidate,
        *,
        rank: int,
        token_window: int,
        force_snippet: bool = False,
    ) -> PaperChunk:
        parent = candidate.parent
        original_token_estimate = _estimate_tokens(parent.content)
        should_snippet = (
            force_snippet
            or original_token_estimate > self._policy.long_parent_token_threshold
        )
        content = parent.content
        snippet_metadata: dict[str, Any] = {
            "parent_snippet": False,
            "parent_snippet_strategy": "full_parent",
        }
        if should_snippet:
            snippet, start, end, strategy = _child_anchor_snippet(
                parent.content,
                candidate.child.content,
                max(1, token_window),
            )
            content = snippet
            snippet_metadata = {
                "parent_snippet": True,
                "parent_snippet_strategy": strategy,
                "parent_snippet_char_start": start,
                "parent_snippet_char_end": end,
            }

        metadata = dict(parent.metadata)
        metadata.update({
            "expanded_from_chunk_id": candidate.child.chunk_id,
            "expansion_reason": "child_parent_context",
            "expansion_edge": "parent_chunk_id",
            "expansion_rank": rank,
            "parent_expansion_reason": "child_parent_context",
            "parent_anchor_child_id": candidate.child.chunk_id,
            "parent_rank": rank,
            "parent_token_estimate": _estimate_tokens(content),
            "parent_original_token_estimate": original_token_estimate,
            "source_parent_chunk_id": parent.chunk_id,
            "parent_child_relevance_score": candidate.child_relevance_score,
            "parent_relevance_score": candidate.parent_relevance_score,
            "parent_section_heading_score": candidate.section_heading_score,
            "parent_position_score": candidate.position_score,
            "parent_final_score": candidate.final_score,
            "parent_score_strategy": candidate.score_strategy,
            "parent_score_weights": dict(candidate.score_weights),
        })
        metadata.update(snippet_metadata)
        if candidate.rerank_score is not None:
            metadata.update({
                "parent_rerank_score": round(candidate.rerank_score, 6),
                "parent_rerank_strategy": "cross_encoder",
                "parent_rerank_query": candidate.rerank_query[:400],
            })
        return parent.model_copy(update={"content": content, "metadata": metadata})

    def _fetch_refs(
        self, children: list[PaperChunk], paper_id: str
    ) -> list[PaperChunk]:
        refs: list[tuple[str, str, str]] = []
        seen = {c.chunk_id for c in children}
        for child in children:
            for ref_id in child.references[:1]:   # first-level only per PRD
                if ref_id not in seen:
                    refs.append((ref_id, child.chunk_id, "chunk_reference"))
                    seen.add(ref_id)
            if child.metadata.get("page_visual"):
                for ref in child.metadata.get("related_visual_chunks", []):
                    if not isinstance(ref, dict):
                        continue
                    ref_id = str(ref.get("chunk_id") or "")
                    if ref_id and ref_id not in seen:
                        refs.append((ref_id, child.chunk_id, "page_visual_related_chunk"))
                        seen.add(ref_id)
            if _is_figure_chunk(child):
                for ref_id, reason, _edge in _figure_context_refs(child):
                    if ref_id and ref_id not in seen:
                        refs.append((ref_id, child.chunk_id, reason))
                        seen.add(ref_id)
            if _is_formula_chunk(child):
                for ref in child.metadata.get("referenced_by_chunks", []):
                    if not isinstance(ref, dict):
                        continue
                    ref_id = str(ref.get("chunk_id") or "")
                    if ref_id and ref_id not in seen:
                        refs.append((ref_id, child.chunk_id, "formula_body_reference"))
                        seen.add(ref_id)
                parent_id = child.parent_chunk_id or ""
                if parent_id and parent_id not in seen:
                    refs.append((parent_id, child.chunk_id, "formula_parent_context"))
                    seen.add(parent_id)
        result: list[PaperChunk] = []
        for ref_id, source_id, reason in refs:
            chunk = self._store.get_chunk(ref_id)
            if chunk:
                result.append(_with_expansion_metadata(
                    chunk,
                    expanded_from_chunk_id=source_id,
                    reason=reason,
                    edge=(
                        "referenced_by_chunks"
                        if reason in {"formula_body_reference", "figure_body_reference"}
                        else reason
                    ),
                    rank=len(result) + 1,
                ))
        return result


def _figure_context_refs(chunk: PaperChunk) -> list[tuple[str, str, str]]:
    refs: list[tuple[str, str, str]] = []
    nearby_id = str(chunk.metadata.get("nearby_context_chunk_id") or "")
    if nearby_id:
        refs.append((nearby_id, "figure_nearby_context", "nearby_context_chunk_id"))
    for ref in chunk.metadata.get("referenced_by_chunks", []):
        if not isinstance(ref, dict):
            continue
        ref_id = str(ref.get("chunk_id") or "")
        if ref_id:
            refs.append((ref_id, "figure_body_reference", "referenced_by_chunks"))
    return refs


def _table_context_refs(chunk: PaperChunk) -> list[tuple[str, str, str]]:
    refs: list[tuple[str, str, str]] = []
    nearby_id = str(chunk.metadata.get("nearby_context_chunk_id") or "")
    if nearby_id:
        refs.append((nearby_id, "table_nearby_context", "nearby_context_chunk_id"))
    for ref in chunk.metadata.get("referenced_by_chunks", []):
        if not isinstance(ref, dict):
            continue
        ref_id = str(ref.get("chunk_id") or "")
        if ref_id:
            refs.append((ref_id, "table_body_reference", "referenced_by_chunks"))
    parent_table_id = str(chunk.metadata.get("parent_table_chunk_id") or "")
    if parent_table_id:
        refs.append((parent_table_id, "table_row_group_parent", "parent_table_chunk_id"))
    parent_id = chunk.parent_chunk_id or ""
    if parent_id:
        refs.append((parent_id, "table_parent_context", "parent_chunk_id"))
    return refs


def _formula_context_refs(chunk: PaperChunk) -> list[tuple[str, str, str]]:
    refs: list[tuple[str, str, str]] = []
    for ref in chunk.metadata.get("referenced_by_chunks", []):
        if not isinstance(ref, dict):
            continue
        ref_id = str(ref.get("chunk_id") or "")
        if ref_id:
            refs.append((ref_id, "formula_body_reference", "referenced_by_chunks"))
    parent_id = chunk.parent_chunk_id or ""
    if parent_id:
        refs.append((parent_id, "formula_parent_context", "parent_chunk_id"))
    return refs


def _should_expand_formula_context(intent: str, question: str) -> bool:
    if intent != "formula_query":
        return False
    lowered = str(question or "").casefold()
    return any(token in lowered for token in ("surrounding text", "explained", "explain", "meaning"))


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
    return _round_score(reducer(values))


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


def _merge_field_embedding_hit(
    metadata: dict[str, Any],
    hit: FieldEmbeddingHit,
) -> dict[str, Any]:
    out = dict(metadata)
    field_name = str(hit.field_name).casefold()
    if field_name not in FIELD_NAMES:
        return out

    raw_scores = out.get("field_embedding_scores")
    scores = {
        str(key): _clamp_score(float(value))
        for key, value in (raw_scores.items() if isinstance(raw_scores, dict) else [])
        if str(key) in FIELD_NAMES
    }
    scores[field_name] = max(scores.get(field_name, 0.0), _clamp_score(hit.score))

    raw_hits = out.get("field_embedding_hits")
    hit_records = [
        dict(item)
        for item in raw_hits
        if isinstance(raw_hits, list) and isinstance(item, dict)
    ] if isinstance(raw_hits, list) else []
    hit_records.append({
        "field_name": field_name,
        "score": _round_score(_clamp_score(hit.score)),
        "field_text_preview": " ".join(hit.field_text.split())[:240],
        "source_locator": hit.metadata.get("source_locator", ""),
        "caption_source_locator": hit.metadata.get("caption_source_locator", ""),
    })
    hit_records.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)

    best_field, best_score = _best_score_item(scores)
    out["field_embedding_scores"] = {name: _round_score(score) for name, score in scores.items()}
    for name in FIELD_NAMES:
        out[f"{name}_embedding_score"] = _round_score(scores.get(name, 0.0))
    out["field_embedding_score"] = _round_score(best_score)
    out["best_embedding_field"] = best_field
    out["field_embedding_hits"] = hit_records[:8]
    out["field_embedding_hit_count"] = len(hit_records)
    return out


def _field_embedding_summary_from_metadata(metadata: dict[str, Any]) -> _FieldEmbeddingSummary:
    raw_scores = metadata.get("field_embedding_scores")
    score_source = raw_scores if isinstance(raw_scores, dict) else {}
    scores: dict[str, float] = {}
    for name in FIELD_NAMES:
        if name not in score_source and f"{name}_embedding_score" not in metadata:
            continue
        try:
            scores[name] = _clamp_score(float(score_source.get(name, metadata.get(f"{name}_embedding_score", 0.0))))
        except (TypeError, ValueError):
            scores[name] = 0.0
    best_field, best_score = _best_score_item(scores)
    raw_hits = metadata.get("field_embedding_hits")
    hits = tuple(
        dict(item)
        for item in raw_hits
        if isinstance(raw_hits, list) and isinstance(item, dict)
    ) if isinstance(raw_hits, list) else ()
    return _FieldEmbeddingSummary(
        scores={name: _round_score(score) for name, score in scores.items()},
        best_field=best_field,
        best_score=_round_score(best_score),
        hits=hits,
    )


def _best_score_item(scores: dict[str, float]) -> tuple[str, float]:
    if not scores:
        return "", 0.0
    field_name, score = max(scores.items(), key=lambda item: (item[1], -FIELD_NAMES.index(item[0])))
    if score <= 0.0:
        return "", 0.0
    return field_name, _clamp_score(score)


def _best_matching_field(field_summary: _FieldEmbeddingSummary, field_scores: _FieldScores) -> str:
    if field_summary.best_field:
        return field_summary.best_field
    deterministic = {
        "title": field_scores.title_score,
        "abstract": field_scores.abstract_score,
        "caption": field_scores.caption_score,
        "equation": field_scores.equation_score,
        "body": field_scores.body_score,
    }
    field_name, score = _best_score_item(deterministic)
    return field_name if score > 0.0 else ""


def _field_rerank_passage(chunk: PaperChunk) -> str:
    field_texts = extract_field_texts(chunk)
    labels = {
        "title": "Title",
        "abstract": "Abstract",
        "caption": "Caption",
        "equation": "Equation",
        "body": "Body",
    }
    lines = []
    for field_name in FIELD_NAMES:
        text = field_texts.text_for(field_name)
        if not text:
            continue
        lines.extend([f"{labels[field_name]}:", text[:1600], ""])
    return "\n".join(lines).strip() or chunk.content[:2000]


def _child_graph_score(chunk: PaperChunk) -> float:
    metadata = chunk.metadata
    if metadata.get("expansion_edge"):
        return 1.0
    if metadata.get("referenced_by_chunks"):
        return 1.0
    if metadata.get("nearby_context_chunk_id"):
        return 0.8
    if chunk.references:
        return 0.6
    if metadata.get("parent_table_chunk_id"):
        return 0.5
    return 0.0


def _element_label_match_score(query_text: str, intent: str, chunk: PaperChunk) -> float:
    labels = _element_query_labels(query_text, intent)
    if not labels:
        return 0.0
    chunk_labels = _chunk_reference_labels(chunk)
    if not chunk_labels:
        return 0.0
    return 1.0 if labels & chunk_labels else 0.0


def _element_query_labels(query_text: str, intent: str) -> set[str]:
    prefixes_by_intent: dict[str, tuple[str, ...]] = {
        "formula_query": ("equation", "formula", "eq"),
        "table_query": ("table", "tab"),
        "figure_query": ("figure", "fig"),
        "numerical_result": ("table", "tab", "figure", "fig"),
    }
    prefixes = prefixes_by_intent.get(intent, ())
    if not prefixes:
        return set()
    normalized = query_text.casefold()
    labels: set[str] = set()
    for prefix in prefixes:
        pattern = rf"\b{re.escape(prefix)}(?:\.|\s+)([a-z0-9][a-z0-9._-]*)"
        for match in re.finditer(pattern, normalized):
            labels.add(_normalize_element_label(match.group(1)))
    return {label for label in labels if label}


def _chunk_reference_labels(chunk: PaperChunk) -> set[str]:
    values: list[Any] = [
        chunk.metadata.get("reference_labels"),
        chunk.metadata.get("equation_number"),
        chunk.metadata.get("equation_id"),
        chunk.metadata.get("table_id"),
        chunk.metadata.get("figure_id"),
        chunk.figure_id,
    ]
    labels: set[str] = set()
    for value in values:
        items = value if isinstance(value, list) else [value]
        for item in items:
            text = str(item or "").casefold().strip()
            if not text:
                continue
            labels.add(_normalize_element_label(text))
            for prefix in ("eq_", "eq", "tbl_", "tbl", "fig_", "fig"):
                if text.startswith(prefix):
                    labels.add(_normalize_element_label(text[len(prefix):]))
    return {label for label in labels if label}


def _normalize_element_label(value: str) -> str:
    text = str(value or "").casefold().strip()
    text = re.sub(r"^(?:equation|formula|eq|table|tab|figure|fig)\.?\s*", "", text)
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text


def _normalized_field_score_weights(weights: dict[str, float]) -> dict[str, float]:
    return _normalized_score_weights(weights, _FIELD_SCORE_KEYS, {
        "title": 0.25,
        "abstract": 0.15,
        "caption": 0.15,
        "equation": 0.15,
        "body": 0.30,
    })


def _normalized_child_fallback_score_weights(weights: dict[str, float]) -> dict[str, float]:
    return _normalized_score_weights(weights, _CHILD_FALLBACK_SCORE_KEYS, {
        "semantic": 0.60,
        "field": 0.25,
        "position": 0.10,
        "graph": 0.05,
    })


def _normalized_child_final_score_weights(weights: dict[str, float]) -> dict[str, float]:
    return _normalized_score_weights(weights, _CHILD_FINAL_SCORE_KEYS, {
        "semantic": 0.45,
        "field_embedding": 0.25,
        "field_rerank": 0.20,
        "position": 0.05,
        "graph": 0.05,
    })


def _normalized_parent_score_weights(weights: dict[str, float]) -> dict[str, float]:
    return _normalized_score_weights(weights, _PARENT_SCORE_KEYS, {
        "child": 0.45,
        "parent": 0.35,
        "heading": 0.15,
        "position": 0.05,
    })


def _normalized_score_weights(
    weights: dict[str, float],
    keys: tuple[str, ...],
    fallback: dict[str, float],
) -> dict[str, float]:
    return normalize_score_weights(weights, keys=keys, fallback=fallback)


def _field_scores_for_chunk(
    query_text: str,
    chunk: PaperChunk,
    weights: dict[str, float],
    *,
    enabled: bool,
) -> _FieldScores:
    if not enabled:
        zero_weights = _normalized_field_score_weights(weights)
        return _FieldScores(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, zero_weights, "disabled")

    normalized_weights = _normalized_field_score_weights(weights)
    field_texts = extract_field_texts(chunk)
    title_score = _lexical_match_score(query_text, field_texts.title)
    abstract_score = _lexical_match_score(query_text, field_texts.abstract)
    caption_score = _lexical_match_score(query_text, field_texts.caption)
    equation_score = _lexical_match_score(query_text, field_texts.equation)
    body_score = _lexical_match_score(query_text, field_texts.body)
    field_score = weighted_component_score(
        {
            "title": title_score,
            "abstract": abstract_score,
            "caption": caption_score,
            "equation": equation_score,
            "body": body_score,
        },
        normalized_weights,
    )
    return _FieldScores(
        title_score=_round_score(title_score),
        abstract_score=_round_score(abstract_score),
        caption_score=_round_score(caption_score),
        equation_score=_round_score(equation_score),
        body_score=_round_score(body_score),
        field_score=_round_score(field_score),
        weights=normalized_weights,
    )


def _child_position_score(
    policy: RetrievalPolicy,
    intent: str,
    section_index: int,
    current_section_index: int,
) -> float:
    alpha = policy.alpha_for(intent)
    if alpha <= 0.0:
        return 0.0
    raw = policy.position_weight(intent, section_index, current_section_index)
    return _clamp_score(raw / alpha)


def _lexical_match_score(query_text: str, field_text: str) -> float:
    query_tokens = _query_tokens(query_text)
    if not query_tokens or not field_text.strip():
        return 0.0
    field_tokens = set(_query_tokens(field_text))
    if not field_tokens:
        return 0.0
    overlap = len(set(query_tokens) & field_tokens) / len(set(query_tokens))
    query_phrase = " ".join(query_tokens)
    field_phrase = " ".join(_query_tokens(field_text))
    if query_phrase and query_phrase in field_phrase:
        overlap = max(overlap, 0.95)
    return _clamp_score(overlap)


def _citation_claim_match_score(question: str, chunk: PaperChunk) -> float:
    claim = _claim_from_citation_question(question)
    if not claim:
        return 0.0
    return _lexical_match_score(claim, chunk.content)


def _text_recall_queries(question: str, intent: str) -> list[str]:
    queries = [str(question or "")]
    if intent == "citation_query":
        claim = _claim_from_citation_question(question)
        if claim:
            queries.append(claim)
    return _unique_nonempty_texts(queries)


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


def _claim_from_citation_question(question: str) -> str:
    match = re.search(r"supports\s+the\s+claim:\s*(.+)", str(question or ""), flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return " ".join(match.group(1).split())


def _query_tokens(text: str) -> list[str]:
    return [match.group(0).casefold() for match in _TOKEN_RE.finditer(text)]


def _abstract_text(chunk: PaperChunk) -> str:
    if chunk.chunk_type == "abstract" or chunk.section_title.casefold() == "abstract":
        return chunk.content
    return ""


def _caption_text(chunk: PaperChunk) -> str:
    candidates = [
        str(chunk.metadata.get("caption_text") or ""),
        str(chunk.metadata.get("surya_caption") or ""),
    ]
    if chunk.chunk_type in {"figure", "table"} or "caption" in chunk.metadata.get("content_sources", []):
        candidates.append(_caption_block(chunk.content))
    return "\n".join(candidate for candidate in candidates if candidate.strip())


def _caption_block(content: str) -> str:
    marker = "caption:"
    normalized = content.casefold()
    index = normalized.find(marker)
    if index < 0:
        return ""
    start = index + len(marker)
    tail = content[start:]
    lines: list[str] = []
    for line in tail.splitlines():
        stripped = line.strip()
        if not stripped:
            if lines:
                break
            continue
        if stripped.endswith(":") and lines:
            break
        lines.append(stripped)
    return " ".join(lines)


def _equation_text(chunk: PaperChunk) -> str:
    parts = [chunk.formula_latex, chunk.formula_description]
    if chunk.has_formula or chunk.chunk_type == "formula":
        parts.append(chunk.content)
    return "\n".join(part for part in parts if part.strip())


def _child_relevance_score(child: PaperChunk, child_rank: int) -> float:
    fallback = 1.0 / max(1, child_rank + 1)
    score = _metadata_float(
        child.metadata,
        "child_final_score",
        _metadata_float(child.metadata, "fused_score", _metadata_float(child.metadata, "text_score", fallback)),
    )
    return _round_score(_clamp_score(score))


def _deterministic_parent_relevance(child_relevance_score: float, heading_score: float) -> float:
    return _clamp_score((child_relevance_score * 0.65) + (heading_score * 0.35))


def _parent_position_score(
    policy: RetrievalPolicy,
    intent: str,
    parent: PaperChunk,
    request: RetrievalRequest,
) -> float:
    alpha = policy.alpha_for(intent)
    if alpha <= 0.0:
        return 0.0
    raw = policy.position_weight(intent, parent.section_index, request.current_section_index)
    return _clamp_score(raw / alpha)


def _parent_section_heading_score(intent: str, parent: PaperChunk) -> float:
    role_keywords: dict[str, tuple[set[str], tuple[str, ...]]] = {
        "concept_method": (
            {"method"},
            ("method", "approach", "architecture", "model", "algorithm", "design", "encoder", "decoder"),
        ),
        "contribution": (
            {"background", "method"},
            ("abstract", "introduction", "contribution", "novel", "propose", "overview", "summary"),
        ),
        "numerical_result": (
            {"experiment", "analysis", "conclusion"},
            (
                "result", "results", "experiment", "experiments", "evaluation", "benchmark",
                "ablation", "analysis", "conclusion", "performance", "accuracy", "score",
            ),
        ),
        "comparison": (
            {"related_work", "experiment", "analysis"},
            ("comparison", "compare", "baseline", "versus", "related work", "prior work", "result", "results"),
        ),
        "table_query": (
            {"experiment", "analysis"},
            ("table", "result", "results", "experiment", "evaluation", "benchmark", "ablation"),
        ),
        "formula_query": (
            {"method"},
            ("formula", "equation", "method", "model", "objective", "loss", "derivation"),
        ),
    }
    roles, keywords = role_keywords.get(intent, (set(), ()))
    normalized_roles = {str(role).casefold() for role in parent.section_role}
    title = parent.section_title.casefold()
    score = 0.0
    if normalized_roles & roles:
        score = max(score, 0.75)
    if any(keyword in title for keyword in keywords):
        score = max(score, 1.0)
    elif any(keyword.replace("_", " ") in title for keyword in roles):
        score = max(score, 0.85)
    return score


def _clamp_score(value: float | None) -> float:
    if value is None:
        return 0.0
    if math.isnan(value) or math.isinf(value):
        return 0.0
    return max(0.0, min(1.0, float(value)))


def _round_score(value: float) -> float:
    return round(float(value), 6)


def _dedupe_chunks(chunks: list[PaperChunk]) -> list[PaperChunk]:
    return dedupe_by_key(chunks, key=lambda chunk: chunk.chunk_id)


def _dedupe_filters(filters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[tuple[str, str], ...]] = set()
    out: list[dict[str, Any]] = []
    for item in filters:
        normalized = tuple(sorted((str(key), repr(value)) for key, value in item.items()))
        if normalized in seen:
            continue
        seen.add(normalized)
        out.append(item)
    return out or [{}]


def _is_table_chunk(chunk: PaperChunk) -> bool:
    return (
        chunk.chunk_type == "table"
        or chunk.has_table
        or bool(chunk.metadata.get("table_id"))
        or bool(chunk.metadata.get("parent_table_chunk_id"))
    )


def _is_figure_chunk(chunk: PaperChunk) -> bool:
    return chunk.chunk_type == "figure" or chunk.has_figure or bool(chunk.figure_id)


def _is_formula_chunk(chunk: PaperChunk) -> bool:
    return chunk.chunk_type == "formula" or chunk.has_formula or bool(chunk.formula_latex)


def _route_match_score(route: RetrievalRoute, chunk: PaperChunk) -> float:
    matched_routes = _matched_recall_routes(route, chunk)
    if not matched_routes:
        return 0.0
    if route.intent == "numerical_result":
        if "table_chunks" in matched_routes:
            return 1.0
        if "result_paragraphs" in matched_routes or "conclusion_context" in matched_routes:
            return 0.8
    if route.intent == "comparison" and "table_chunks" in matched_routes:
        return 0.75
    return 1.0


def _matched_recall_routes(route: RetrievalRoute, chunk: PaperChunk) -> tuple[str, ...]:
    routes: list[str] = []
    route_set = set(route.recall_routes)
    if "figure_chunks" in route_set and _is_figure_chunk(chunk):
        routes.append("figure_chunks")
    if "table_chunks" in route_set and _is_table_chunk(chunk):
        routes.append("table_chunks")
    if "formula_chunks" in route_set and _is_formula_chunk(chunk):
        routes.append("formula_chunks")
    if "abstract_body" in route_set and chunk.chunk_type in {"abstract", "paragraph"}:
        routes.append("abstract_body")
    if "method_body" in route_set and _has_section_role(chunk, {"method"}):
        routes.append("method_body")
    if "result_paragraphs" in route_set and _has_result_context(chunk):
        routes.append("result_paragraphs")
    if "conclusion_context" in route_set and _has_section_role(chunk, {"analysis", "conclusion"}):
        routes.append("conclusion_context")
    if "comparison_paragraphs" in route_set and _has_section_role(chunk, {"related_work"}):
        routes.append("comparison_paragraphs")
    return tuple(routes)


def _has_section_role(chunk: PaperChunk, roles: set[str]) -> bool:
    return bool({str(role).casefold() for role in chunk.section_role} & roles)


def _has_result_context(chunk: PaperChunk) -> bool:
    if chunk.chunk_type != "paragraph":
        return False
    if _has_section_role(chunk, {"experiment", "analysis", "conclusion"}):
        return True
    return _result_title_rank(chunk.section_title) < 100 or _result_title_rank(chunk.content[:240]) < 100


def _should_expand_result_context(intent: str, question: str) -> bool:
    if intent in _TABLE_EXPANSION_INTENTS:
        return True
    normalized = question.casefold()
    return any(keyword in normalized for keyword in _RESULT_QUESTION_KEYWORDS)


def _result_context_priority(chunk: PaperChunk, table: PaperChunk) -> tuple[int, int, int] | None:
    if chunk.chunk_type != "paragraph":
        return None
    role_rank = _result_role_rank(chunk)
    title_rank = _result_title_rank(chunk.section_title)
    content_rank = _result_title_rank(chunk.content[:240])
    semantic_rank = min(title_rank, content_rank)
    if semantic_rank >= 100:
        return None
    section_distance = abs(chunk.section_index - table.section_index)
    proximity_rank = 0 if section_distance == 0 else 1 if section_distance == 1 else 2
    role_bonus = 0 if role_rank < 100 else 1
    return proximity_rank, semantic_rank + role_bonus, section_distance


def _result_role_rank(chunk: PaperChunk) -> int:
    ranks = {"experiment": 0, "analysis": 1, "conclusion": 2}
    values = [
        ranks.get(str(role).casefold(), 100)
        for role in chunk.section_role
        if str(role).casefold() in _RESULT_SECTION_ROLES
    ]
    return min(values) if values else 100


def _result_title_rank(text: str) -> int:
    normalized = text.casefold()
    for index, keyword in enumerate(_RESULT_CONTEXT_KEYWORDS):
        if keyword in normalized:
            return index
    return 100


def _table_context_rerank_query(table: PaperChunk, request: RetrievalRequest) -> str:
    table_text = " ".join(table.content.split())
    return "\n".join([
        request.question.strip(),
        f"Table section: {table.section_title}",
        f"Table evidence: {table_text[:1000]}",
    ]).strip()


def _estimate_tokens(text: str) -> int:
    compact = " ".join(text.split())
    if not compact:
        return 0
    return max(1, math.ceil(len(compact) / 4))


def _parent_context_rerank_query(
    request: RetrievalRequest,
    route: RetrievalRoute,
    candidates: list[_ParentCandidate],
) -> str:
    anchors = []
    seen: set[str] = set()
    for candidate in candidates[:5]:
        if candidate.child.chunk_id in seen:
            continue
        seen.add(candidate.child.chunk_id)
        anchors.append(f"- {candidate.child.content[:240]}")
    return "\n".join([
        request.question.strip(),
        f"Intent: {route.intent}",
        "Matched child evidence:",
        *anchors,
    ]).strip()


def _parent_context_rerank_passage(candidate: _ParentCandidate) -> str:
    return "\n".join([
        f"Parent section: {candidate.parent.section_title}",
        f"Child anchor: {candidate.child.content[:500]}",
        f"Parent context: {candidate.parent.content[:1500]}",
    ]).strip()


def _child_anchor_snippet(parent_text: str, child_text: str, token_window: int) -> tuple[str, int, int, str]:
    char_window = max(80, token_window * 4)
    if len(parent_text) <= char_window:
        return parent_text.strip(), 0, len(parent_text), "full_parent_under_window"

    anchor_start = _find_child_anchor(parent_text, child_text)
    if anchor_start < 0:
        end = min(len(parent_text), char_window)
        return parent_text[:end].strip(), 0, end, "leading_window"

    child_len = min(max(len(child_text.strip()), 1), char_window // 2)
    start = max(0, anchor_start - (char_window - child_len) // 2)
    end = min(len(parent_text), start + char_window)
    if end - start < char_window:
        start = max(0, end - char_window)
    return parent_text[start:end].strip(), start, end, "child_anchor_window"


def _find_child_anchor(parent_text: str, child_text: str) -> int:
    parent_lower = parent_text.casefold()
    normalized_child = " ".join(child_text.split())
    candidates = [
        child_text.strip(),
        normalized_child,
        normalized_child[:300],
        normalized_child[:160],
    ]
    for candidate in candidates:
        if len(candidate) < 24:
            continue
        index = parent_lower.find(candidate.casefold())
        if index >= 0:
            return index
    return -1


def _with_expansion_metadata(
    chunk: PaperChunk,
    *,
    expanded_from_chunk_id: str,
    reason: str,
    edge: str,
    rank: int,
) -> PaperChunk:
    metadata = dict(chunk.metadata)
    metadata.update(expansion_metadata(
        expanded_from_id=expanded_from_chunk_id,
        reason=reason,
        edge=edge,
        rank=rank,
    ))
    return chunk.model_copy(update={"metadata": metadata})



__all__ = [
    "DEFAULT_RETRIEVAL_POLICY",
    "NEWS_PAPER_RAG_POLICY_ENV",
    "PAPER_VISUAL_RAG_TUNED_POLICY",
    "ResearchRetriever",
    "RetrievalPolicy",
    "RetrievalRequest",
    "RetrievalResult",
    "build_retrieval_policy",
    "build_retrieval_policy_from_env",
]
