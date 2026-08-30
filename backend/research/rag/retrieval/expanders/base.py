from __future__ import annotations

from typing import Any, Protocol

from backend.research.document.models import PaperChunk


class ContextExpander(Protocol):
    name: str

    def expand(self, chunks: list[PaperChunk], request: Any, route: Any) -> Any: ...


__all__ = ["ContextExpander"]
