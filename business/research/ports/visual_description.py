from __future__ import annotations

from typing import Protocol, runtime_checkable

from business.research.document.models import PaperChunk


@runtime_checkable
class VisualChunkDescriptionPort(Protocol):
    """Adds model-generated visual descriptions to image-backed paper chunks."""

    def describe_chunks(self, chunks: list[PaperChunk]) -> list[PaperChunk]: ...


__all__ = ["VisualChunkDescriptionPort"]
