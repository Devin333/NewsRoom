from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from business.research.document.models import PaperChunk


@runtime_checkable
class ChunkStorePort(Protocol):
    def search_chunks(
        self,
        paper_id: str,
        query_text: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
        score_threshold: float | None = None,
    ) -> list[PaperChunk]: ...

    def get_chunk(self, chunk_id: str) -> PaperChunk | None: ...
    def get_parent_chunk(self, chunk: PaperChunk) -> PaperChunk | None: ...


__all__ = ["ChunkStorePort"]
