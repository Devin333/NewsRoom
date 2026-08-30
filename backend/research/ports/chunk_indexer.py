from __future__ import annotations

from typing import Protocol, runtime_checkable

from backend.research.document.models import PaperChunk


@runtime_checkable
class ChunkIndexerPort(Protocol):
    def index_chunks(self, chunks: list[PaperChunk]) -> None: ...
    def delete_paper_chunks(self, paper_id: str) -> None: ...


__all__ = ["ChunkIndexerPort"]
