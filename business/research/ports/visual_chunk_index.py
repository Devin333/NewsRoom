from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from business.research.document.models import PaperChunk


@runtime_checkable
class VisualEmbeddingPort(Protocol):
    """Embeds text queries and image files into the same visual vector space."""

    dimension: int

    def embed_text(self, text: str) -> list[float]: ...

    def embed_image(self, image_path: str) -> list[float]: ...

    def embed_images(self, image_paths: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class VisualChunkHit:
    chunk_id: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class VisualChunkIndexerPort(Protocol):
    def ensure_collection(self) -> None: ...

    def index_chunks(self, chunks: list[PaperChunk]) -> None: ...

    def delete_paper_chunks(self, paper_id: str) -> None: ...


@runtime_checkable
class VisualChunkSearchPort(Protocol):
    def search_visual_chunks(
        self,
        paper_id: str,
        query_text: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> list[VisualChunkHit]: ...


__all__ = [
    "VisualChunkHit",
    "VisualChunkIndexerPort",
    "VisualChunkSearchPort",
    "VisualEmbeddingPort",
]
