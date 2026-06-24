from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from business.research.document.models import PaperChunk
from business.research.rag.routing import QueryIntent, RetrievalRoute, build_retrieval_route
from business.research.ports.chunk_store import ChunkStorePort
from business.research.ports.visual_chunk_index import VisualChunkHit, VisualChunkSearchPort

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
    "result",
    "results",
    "experiment",
    "experiments",
    "evaluation",
    "ablation",
    "analysis",
    "conclusion",
    "benchmark",
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


@dataclass(frozen=True)
class RetrievalPolicy:
    """Tunable retrieval parameters (position weighting + over-fetch + rerank filter)."""
    position_alpha: dict[str, float] = field(default_factory=lambda: dict(_DEFAULT_ALPHA))
    default_alpha: float = 0.2          # fallback α for unlisted intents
    sigma: float = 3.0                  # position decay rate, in sections
    overfetch_multiplier: int = 3       # fetch limit*N candidates before re-rank
    rerank_score_threshold: float = 0.3  # drop candidates below this reranker score (0 = off)
    visual_fusion_text_weight: float = 0.65
    visual_fusion_visual_weight: float = 0.35
    max_table_context_chunks: int = 4
    table_result_context_search_limit: int = 12
    supplemental_table_result_limit: int = 2

    def alpha_for(self, intent: str) -> float:
        return self.position_alpha.get(intent, self.default_alpha)

    def position_weight(self, intent: str, section_index: int, current: int) -> float:
        alpha = self.alpha_for(intent)
        if alpha == 0.0:
            return 0.0
        return alpha * math.exp(-abs(section_index - current) / self.sigma)


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
        visual_store: VisualChunkSearchPort | None = None,
    ) -> None:
        self._store = chunk_store
        self._policy = policy or RetrievalPolicy()
        self._reranker = reranker
        self._visual_store = visual_store

    def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        import time
        t0 = time.perf_counter()
        route = build_retrieval_route(request.question)
        filters = self._build_filters(route)

        # ── 1. vector search (over-fetch for re-ranking) ──────────────────────
        candidates = self._store.search_with_scores(
            request.paper_id,
            request.question,
            filters=filters,
            limit=request.limit * self._policy.overfetch_multiplier,
        )
        n_recalled = len(candidates)
        visual_hits = self._search_visual_candidates(request, route, filters)
        n_visual_recalled = len(visual_hits)

        # ── 2. base relevance: reranker (if available) else vector score ──────
        base_scores = self._base_scores(request.question, candidates)

        # ── 2b. rerank score threshold: drop low-relevance candidates (reranker only) ──
        pairs = list(zip(candidates, base_scores))
        n_before_filter = len(pairs)
        if self._reranker is not None and self._policy.rerank_score_threshold > 0.0:
            kept = [(c, b) for (c, b) in pairs if b >= self._policy.rerank_score_threshold]
            pairs = kept or pairs[:1]  # never drop everything — keep top-1 as fallback
        n_filtered = n_before_filter - len(pairs)

        # ── 3. position-aware re-rank ─────────────────────────────────────────
        scored = [
            (
                _with_retrieval_scores(
                    chunk,
                    text_score=base,
                    visual_score=None,
                    fused_score=base,
                    strategy="text",
                ),
                base + self._policy.position_weight(
                    route.intent, chunk.section_index, request.current_section_index
                ),
            )
            for (chunk, _sem), base in pairs
        ]
        if visual_hits:
            scored = self._fuse_visual_scores(
                scored,
                visual_hits,
                paper_id=request.paper_id,
                current_section_index=request.current_section_index,
                intent=route.intent,
            )
        scored.sort(key=lambda x: x[1], reverse=True)
        child_chunks = [c for c, _ in scored[: request.limit]]
        supplemental_table_chunks = self._supplemental_table_hits(child_chunks, request, route)
        child_chunks.extend(supplemental_table_chunks)
        top_score = scored[0][1] if scored else 0.0

        # ── 3. parent expansion ───────────────────────────────────────────────
        parent_chunks = self._fetch_parents(child_chunks, request.paper_id)

        # ── 4. cross-reference expansion ──────────────────────────────────────
        cross_ref_chunks = self._fetch_refs(child_chunks, request.paper_id)
        table_context_chunks = self._fetch_table_context(child_chunks, request, route)
        ref_chunks = _dedupe_chunks([*cross_ref_chunks, *table_context_chunks])

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        metrics = {
            "intent": route.intent,
            "reranker": self._reranker is not None,
            "recalled": n_recalled,
            "visual_recalled": n_visual_recalled,
            "visual_fusion_enabled": self._visual_store is not None,
            "threshold_filtered": n_filtered,
            "child_returned": len(child_chunks),
            "parent_returned": len(parent_chunks),
            "ref_returned": len(ref_chunks),
            "supplemental_table_returned": len(supplemental_table_chunks),
            "table_context_returned": len(table_context_chunks),
            "top_score": round(top_score, 4),
            "elapsed_ms": elapsed_ms,
        }
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
        self, question: str, candidates: list[tuple[PaperChunk, float]]
    ) -> list[float]:
        """Base relevance per candidate: reranker cross-encoder score if available,
        else the vector semantic score. Reranker scores replace (not add to) vector
        scores since the cross-encoder is a stronger relevance signal."""
        if self._reranker is None or not candidates:
            return [sem for _chunk, sem in candidates]
        passages = [chunk.content for chunk, _ in candidates]
        try:
            return self._reranker.score(question, passages)
        except Exception:
            import logging
            logging.getLogger(__name__).warning("reranker failed, falling back to vector scores")
            return [sem for _chunk, sem in candidates]

    def _build_filters(self, route: RetrievalRoute) -> dict[str, Any]:
        filters: dict[str, Any] = {}
        if route.extra_filters:
            filters.update(route.extra_filters)
        return filters

    def _search_visual_candidates(
        self,
        request: RetrievalRequest,
        route: RetrievalRoute,
        filters: dict[str, Any],
    ) -> list[VisualChunkHit]:
        if self._visual_store is None or route.intent != "figure_query":
            return []
        try:
            return self._visual_store.search_visual_chunks(
                request.paper_id,
                request.question,
                filters=filters,
                limit=request.limit * self._policy.overfetch_multiplier,
            )
        except Exception:
            logging.getLogger(__name__).warning("visual retrieval failed", exc_info=True)
            return []

    def _fuse_visual_scores(
        self,
        scored: list[tuple[PaperChunk, float]],
        visual_hits: list[VisualChunkHit],
        *,
        paper_id: str,
        current_section_index: int,
        intent: QueryIntent,
    ) -> list[tuple[PaperChunk, float]]:
        by_id: dict[str, tuple[PaperChunk, float, float | None]] = {}
        for chunk, score in scored:
            by_id[chunk.chunk_id] = (
                chunk,
                _metadata_float(chunk.metadata, "text_score", score),
                None,
            )

        for hit in visual_hits:
            existing = by_id.get(hit.chunk_id)
            chunk = existing[0] if existing else None
            if chunk is None:
                chunk = self._store.get_chunk(hit.chunk_id)
            if chunk is None or chunk.paper_id != paper_id:
                continue
            text_score = existing[1] if existing else 0.0
            by_id[chunk.chunk_id] = (chunk, text_score, hit.score)

        fused: list[tuple[PaperChunk, float]] = []
        for chunk, text_score, visual_score in by_id.values():
            fused_score, strategy = self._fusion_score(
                text_score=text_score,
                visual_score=visual_score,
            )
            fused_chunk = _with_retrieval_scores(
                chunk,
                text_score=text_score,
                visual_score=visual_score,
                fused_score=fused_score,
                strategy=strategy,
            )
            fused.append(
                (
                    fused_chunk,
                    fused_score + self._policy.position_weight(
                        intent, chunk.section_index, current_section_index
                    ),
                )
            )
        return fused

    def _fusion_score(self, *, text_score: float, visual_score: float | None) -> tuple[float, str]:
        text = max(0.0, text_score)
        if visual_score is None:
            return text_score, "text"
        visual = max(0.0, visual_score)
        if text:
            score = (
                self._policy.visual_fusion_text_weight * text
                + self._policy.visual_fusion_visual_weight * visual
            )
            return score, "text_image_fusion"
        return visual * self._policy.visual_fusion_visual_weight, "image_only"

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
            scored = _with_retrieval_scores(
                chunk,
                text_score=score,
                visual_score=None,
                fused_score=score,
                strategy="supplemental_table_text",
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

        candidates: list[tuple[tuple[int, int, int, float], PaperChunk]] = []
        for chunk, score in scored:
            if chunk.paper_id != request.paper_id or chunk.chunk_id in seen:
                continue
            priority = _result_context_priority(chunk, table)
            if priority is None:
                continue
            candidates.append(((*priority, -score), chunk))
        candidates.sort(key=lambda item: item[0])
        return [chunk for _priority, chunk in candidates[:limit]]

    def _fetch_parents(
        self, children: list[PaperChunk], paper_id: str
    ) -> list[PaperChunk]:
        seen: set[str] = set()
        parents: list[PaperChunk] = []
        for child in children:
            pid = child.parent_chunk_id
            if not pid or pid in seen:
                continue
            seen.add(pid)
            parent = self._store.get_chunk(pid)
            if parent:
                parents.append(parent)
        # fall back to children themselves if no parents found (e.g. abstract)
        if not parents:
            return list(children)
        return parents

    def _fetch_refs(
        self, children: list[PaperChunk], paper_id: str
    ) -> list[PaperChunk]:
        ref_ids: list[str] = []
        seen = {c.chunk_id for c in children}
        for child in children:
            for ref_id in child.references[:1]:   # first-level only per PRD
                if ref_id not in seen:
                    ref_ids.append(ref_id)
                    seen.add(ref_id)
        result: list[PaperChunk] = []
        for ref_id in ref_ids:
            chunk = self._store.get_chunk(ref_id)
            if chunk:
                result.append(chunk)
        return result


def _metadata_float(metadata: dict[str, Any], key: str, default: float) -> float:
    value = metadata.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _dedupe_chunks(chunks: list[PaperChunk]) -> list[PaperChunk]:
    seen: set[str] = set()
    out: list[PaperChunk] = []
    for chunk in chunks:
        if chunk.chunk_id in seen:
            continue
        seen.add(chunk.chunk_id)
        out.append(chunk)
    return out


def _is_table_chunk(chunk: PaperChunk) -> bool:
    return (
        chunk.chunk_type == "table"
        or chunk.has_table
        or bool(chunk.metadata.get("table_id"))
        or bool(chunk.metadata.get("parent_table_chunk_id"))
    )


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
    best_rank = min(role_rank, title_rank, content_rank)
    if best_rank >= 100:
        return None
    section_distance = abs(chunk.section_index - table.section_index)
    proximity_rank = 0 if section_distance == 0 else 1 if section_distance == 1 else 2
    return proximity_rank, best_rank, section_distance


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


def _with_expansion_metadata(
    chunk: PaperChunk,
    *,
    expanded_from_chunk_id: str,
    reason: str,
    edge: str,
    rank: int,
) -> PaperChunk:
    metadata = dict(chunk.metadata)
    metadata.update({
        "expanded_from_chunk_id": expanded_from_chunk_id,
        "expansion_reason": reason,
        "expansion_edge": edge,
        "expansion_rank": rank,
    })
    return chunk.model_copy(update={"metadata": metadata})


def _with_retrieval_scores(
    chunk: PaperChunk,
    *,
    text_score: float,
    visual_score: float | None,
    fused_score: float,
    strategy: str,
) -> PaperChunk:
    metadata = dict(chunk.metadata)
    metadata["text_score"] = round(float(text_score), 6)
    metadata["fused_score"] = round(float(fused_score), 6)
    metadata["fusion_strategy"] = strategy
    metadata["visual_hit"] = visual_score is not None
    if visual_score is not None:
        metadata["visual_score"] = round(float(visual_score), 6)
    return chunk.model_copy(update={"metadata": metadata})


__all__ = ["ResearchRetriever", "RetrievalPolicy", "RetrievalRequest", "RetrievalResult"]
