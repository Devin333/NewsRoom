from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.memory.indexing.document import MemoryDocument


@dataclass(frozen=True)
class MemoryChunk:
    chunk_id: str
    document_id: str
    text: str
    index: int
    metadata: dict[str, Any] = field(default_factory=dict)


class MemoryChunker:
    def __init__(self, *, max_chars: int = 2000, overlap_chars: int = 200) -> None:
        self.max_chars = max(1, int(max_chars))
        self.overlap_chars = max(0, min(int(overlap_chars), self.max_chars - 1))

    def chunk(self, document: MemoryDocument) -> list[MemoryChunk]:
        return [
            MemoryChunk(
                chunk_id=self._chunk_id(document.document_id, index),
                document_id=document.document_id,
                text=text,
                index=index,
                metadata=dict(document.metadata),
            )
            for index, text in enumerate(self._split_text(document.text))
        ]

    def _split_text(self, text: str) -> list[str]:
        if not text:
            return []
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = min(len(text), start + self.max_chars)
            chunks.append(text[start:end])
            if end >= len(text):
                break
            start = end - self.overlap_chars
        return chunks

    def _chunk_id(self, document_id: str, index: int) -> str:
        return f"{document_id}:chunk:{index}"
