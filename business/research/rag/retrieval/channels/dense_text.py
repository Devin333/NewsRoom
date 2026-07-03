from __future__ import annotations

import logging
from typing import Any

from business.research.document.models import PaperChunk
from business.research.ports.chunk_store import ChunkStorePort
from business.research.rag.retrieval.channels.base import RankedHit, RankedList


class DenseTextChannel:
    name = "dense_text"

    def __init__(self, chunk_store: ChunkStorePort) -> None:
        self._store = chunk_store

    def recall(
        self,
        request: Any,
        plan: Any,
    ) -> RankedList:
        hits = self.recall_chunks(
            paper_id=request.paper_id,
            query_text=request.question,
            filters=getattr(plan, "filters", {}) or {},
            limit=getattr(plan, "limit", 10),
            suppress_errors=bool(getattr(plan, "suppress_errors", False)),
        )
        return [
            RankedHit(
                chunk_id=chunk.chunk_id,
                score=score,
                channel=self.name,
                metadata=dict(chunk.metadata),
            )
            for chunk, score in hits
        ]

    def recall_chunks(
        self,
        *,
        paper_id: str,
        query_text: str,
        filters: dict[str, Any],
        limit: int,
        suppress_errors: bool = False,
    ) -> list[tuple[PaperChunk, float]]:
        try:
            return self._store.search_with_scores(
                paper_id,
                query_text,
                filters=filters,
                limit=limit,
            )
        except Exception:
            if not suppress_errors:
                raise
            logging.getLogger(__name__).warning("semantic retrieval failed", exc_info=True)
            return []


__all__ = ["DenseTextChannel"]
