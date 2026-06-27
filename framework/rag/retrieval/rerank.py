from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence


def _clamp_score(value: float | int | str | None) -> float:
    if value is None:
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(number) or math.isinf(number):
        return 0.0
    return max(0.0, min(1.0, number))


@dataclass(frozen=True)
class RerankScoreSet:
    scores: tuple[float, ...]

    @classmethod
    def from_raw(cls, scores: Sequence[float | int | str], *, expected_count: int) -> "RerankScoreSet | None":
        if len(scores) != expected_count:
            return None
        return cls(scores=tuple(_clamp_score(score) for score in scores))

    def as_id_map(self, ids: Sequence[str]) -> dict[str, float]:
        if len(ids) != len(self.scores):
            raise ValueError("ids length must match scores length")
        return {str(item_id): score for item_id, score in zip(ids, self.scores, strict=True)}

    def keep_indexes(self, *, threshold: float = 0.0) -> tuple[int, ...]:
        normalized_threshold = _clamp_score(threshold)
        return tuple(index for index, score in enumerate(self.scores) if score >= normalized_threshold)


def rerank_sort_key(
    *,
    rerank_score: float,
    priority: tuple[int, ...] = (),
    fallback_score: float = 0.0,
) -> tuple[float, tuple[int, ...], float]:
    return (-_clamp_score(rerank_score), priority, -float(fallback_score))


__all__ = ["RerankScoreSet", "rerank_sort_key"]
