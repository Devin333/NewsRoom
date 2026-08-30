from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class RerankerPort(Protocol):
    """Cross-encoder reranker: scores (query, passage) relevance.

    Returns a relevance score per passage, higher = more relevant. The order of
    returned scores matches the input passages order.
    """

    def score(self, query: str, passages: list[str]) -> list[float]:
        ...


__all__ = ["RerankerPort"]
