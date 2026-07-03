from __future__ import annotations

import math

from framework.harness.rag.relevance import RelevanceScorerPort

from business.research.ports.reranker import RerankerPort


class RerankerRelevanceScorer(RelevanceScorerPort):
    """Adapt a paper reranker into the Harness relevance scorer contract."""

    def __init__(
        self,
        reranker: RerankerPort,
        *,
        midpoint: float = 0.0,
        scale: float = 1.0,
    ) -> None:
        if scale <= 0:
            raise ValueError("scale must be greater than 0")
        self._reranker = reranker
        self._midpoint = float(midpoint)
        self._scale = float(scale)

    def score(self, question: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        raw_scores = self._reranker.score(question, passages)
        return [_sigmoid(float(score), midpoint=self._midpoint, scale=self._scale) for score in raw_scores]


def _sigmoid(value: float, *, midpoint: float, scale: float) -> float:
    shifted = (value - midpoint) / scale
    if shifted >= 0:
        z = math.exp(-shifted)
        return 1.0 / (1.0 + z)
    z = math.exp(shifted)
    return z / (1.0 + z)


__all__ = ["RerankerRelevanceScorer"]
