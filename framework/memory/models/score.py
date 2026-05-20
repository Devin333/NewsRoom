from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MemoryScore:
    relevance: float = 0.0
    confidence: float | None = None
    importance: float | None = None
    freshness: float | None = None
    final_score: float | None = None

    def __post_init__(self) -> None:
        for name, value in self.to_dict().items():
            if value is not None:
                _validate_score(name, value)

    def compute(self, *, weights: dict[str, float] | None = None) -> float:
        if self.final_score is not None:
            return self.final_score
        weight_map = weights or {
            "relevance": 0.5,
            "confidence": 0.2,
            "importance": 0.2,
            "freshness": 0.1,
        }
        weighted = 0.0
        total = 0.0
        values = {
            "relevance": self.relevance,
            "confidence": self.confidence,
            "importance": self.importance,
            "freshness": self.freshness,
        }
        for name, value in values.items():
            if value is None:
                continue
            weight = float(weight_map.get(name, 0.0))
            weighted += float(value) * weight
            total += weight
        return weighted / total if total else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "relevance": self.relevance,
            "confidence": self.confidence,
            "importance": self.importance,
            "freshness": self.freshness,
            "final_score": self.final_score,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MemoryScore":
        return cls(
            relevance=_optional_float(payload.get("relevance")) or 0.0,
            confidence=_optional_float(payload.get("confidence")),
            importance=_optional_float(payload.get("importance")),
            freshness=_optional_float(payload.get("freshness")),
            final_score=_optional_float(payload.get("final_score")),
        )


def _validate_score(name: str, value: float) -> None:
    numeric = float(value)
    if numeric < 0.0 or numeric > 1.0:
        raise ValueError(f"{name} must be between 0 and 1")


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)
