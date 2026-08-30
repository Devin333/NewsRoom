from __future__ import annotations

import logging
from typing import Any

from backend.research.document.models import PaperChunk
from backend.research.ports.chunk_store import ChunkStorePort
from backend.research.rag.retrieval.expanders.table_context import should_expand_result_context
from backend.research.rag.retrieval.filtering import (
    chunk_visible_for_request,
    filter_chunks_for_request,
    merge_request_filters,
)
from backend.research.rag.retrieval.paper_visual_retrieval import with_retrieval_scores
from backend.research.rag.retrieval.scoring import ChildCandidateScorer


class SupplementalTableHitExpander:
    name = "supplemental_table_hits"

    def __init__(self, chunk_store: ChunkStorePort, policy: Any) -> None:
        self._store = chunk_store
        self._policy = policy
        self._child_scorer = ChildCandidateScorer(policy)

    def expand(self, child_chunks: list[PaperChunk], request: Any, route: Any) -> list[PaperChunk]:
        child_chunks = filter_chunks_for_request(child_chunks, request)
        if not should_expand_result_context(route.intent, request.question):
            return []
        if any(_is_table_chunk(chunk) for chunk in child_chunks):
            return []
        seen = {chunk.chunk_id for chunk in child_chunks}
        try:
            candidates = self._store.search_with_scores(
                request.paper_id,
                request.question,
                filters=merge_request_filters(request, {"chunk_type": "table"}),
                limit=self._policy.supplemental_table_result_limit,
            )
        except Exception:
            logging.getLogger(__name__).warning("supplemental table retrieval failed", exc_info=True)
            return []

        out: list[PaperChunk] = []
        for chunk, score in candidates:
            if (
                chunk.paper_id != request.paper_id
                or chunk.chunk_id in seen
                or not _is_table_chunk(chunk)
                or not chunk_visible_for_request(chunk, request)
            ):
                continue
            seen.add(chunk.chunk_id)
            scored = with_retrieval_scores(
                chunk,
                text_score=score,
                visual_score=None,
                fused_score=score,
                strategy="supplemental_table_text",
            )
            scored, _final_score = self._child_scorer.score(
                scored,
                request,
                route,
                semantic_score=score,
            )
            metadata = dict(scored.metadata)
            metadata["supplemental_reason"] = "result_intent_table_search"
            out.append(scored.model_copy(update={"metadata": metadata}))
        return out


def _is_table_chunk(chunk: PaperChunk) -> bool:
    return (
        chunk.chunk_type == "table"
        or chunk.has_table
        or bool(chunk.metadata.get("table_id"))
        or bool(chunk.metadata.get("parent_table_chunk_id"))
    )


__all__ = ["SupplementalTableHitExpander"]
