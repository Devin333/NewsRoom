from __future__ import annotations

from typing import Protocol, runtime_checkable

from framework.harness.rag.models import RAGContextPack, RAGSessionRequest


@runtime_checkable
class RAGSessionController(Protocol):
    def build_context_pack(self, request: RAGSessionRequest) -> RAGContextPack:
        ...


__all__ = ["RAGSessionController"]
