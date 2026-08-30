from __future__ import annotations

from typing import Protocol, runtime_checkable

from backend.research.document.models import PaperChunk


@runtime_checkable
class ChunkRepositoryPort(Protocol):
    """Persists chunk metadata + parent-child relationships (e.g. PostgreSQL)."""

    def save_chunks(self, chunks: list[PaperChunk]) -> None: ...
    def delete_paper_chunks(self, paper_id: str) -> None: ...


__all__ = ["ChunkRepositoryPort"]
