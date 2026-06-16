from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from business.research.document.models import PaperChunk
from business.research.rag.routing import QueryIntent, RetrievalRoute, build_retrieval_route
from infrastructure.storage.vector.paper_chunk_store import PaperChunkStore

# Position weight α per intent (0 = no position bias)
_ALPHA: dict[str, float] = {
    "figure_query":    0.0,
    "formula_query":   0.0,
    "contribution":    0.05,
    "concept_method":  0.2,
    "numerical_result": 0.2,
    "comparison":      0.2,
}
_SIGMA = 3.0  # decay rate in sections


def _position_weight(alpha: float, section_index: int, current: int) -> float:
    if alpha == 0.0:
        return 0.0
    return alpha * math.exp(-abs(section_index - current) / _SIGMA)


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
        for chunk in self.parent_chunks:
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
                },
            })
        return out


class ResearchRetriever:
    """
    Agent-callable retrieval tool.

    Flow: intent classification → vector search (limit*3) →
          position-aware re-rank → parent expansion → cross-ref expansion
    """

    def __init__(self, chunk_store: PaperChunkStore) -> None:
        self._store = chunk_store

    def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        route = build_retrieval_route(request.question)
        filters = self._build_filters(route)
        alpha = _ALPHA.get(route.intent, 0.2)

        # ── 1. vector search (over-fetch for re-ranking) ──────────────────────
        candidates = self._store.search_with_scores(
            request.paper_id,
            request.question,
            filters=filters,
            limit=request.limit * 3,
        )

        # ── 2. position-aware re-rank ─────────────────────────────────────────
        scored = [
            (chunk, sem + _position_weight(alpha, chunk.section_index, request.current_section_index))
            for chunk, sem in candidates
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        child_chunks = [c for c, _ in scored[: request.limit]]

        # ── 3. parent expansion ───────────────────────────────────────────────
        parent_chunks = self._fetch_parents(child_chunks, request.paper_id)

        # ── 4. cross-reference expansion ──────────────────────────────────────
        ref_chunks = self._fetch_refs(child_chunks, request.paper_id)

        return RetrievalResult(
            parent_chunks=parent_chunks,
            child_chunks=child_chunks,
            ref_chunks=ref_chunks,
            intent=route.intent,
        )

    # ── private ───────────────────────────────────────────────────────────────

    def _build_filters(self, route: RetrievalRoute) -> dict[str, Any]:
        filters: dict[str, Any] = {}
        if route.extra_filters:
            filters.update(route.extra_filters)
        return filters

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


__all__ = ["ResearchRetriever", "RetrievalRequest", "RetrievalResult"]
