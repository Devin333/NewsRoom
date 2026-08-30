from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MemoryMetric:
    name: str
    value: float
    threshold: float | None = None
    passed: bool | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "threshold": self.threshold,
            "passed": self.passed,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class MemoryEvaluationMetrics:
    claim_support_rate: float = 0.0
    claim_contradiction_rate: float = 0.0
    event_duplicate_rate: float = 0.0
    recall_usefulness_score: float = 0.0
    memory_noise_ratio: float = 0.0
    timeline_coverage_score: float = 0.0
    decision_regret_score: float = 0.0
    source_false_positive_rate: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def overall_score(self) -> float:
        positive = (
            self.claim_support_rate
            + self.recall_usefulness_score
            + self.timeline_coverage_score
        ) / 3
        negative = (
            self.claim_contradiction_rate
            + self.event_duplicate_rate
            + self.memory_noise_ratio
            + self.decision_regret_score
            + self.source_false_positive_rate
        ) / 5
        return _clamp(positive * 0.7 + (1.0 - negative) * 0.3)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_support_rate": self.claim_support_rate,
            "claim_contradiction_rate": self.claim_contradiction_rate,
            "event_duplicate_rate": self.event_duplicate_rate,
            "recall_usefulness_score": self.recall_usefulness_score,
            "memory_noise_ratio": self.memory_noise_ratio,
            "timeline_coverage_score": self.timeline_coverage_score,
            "decision_regret_score": self.decision_regret_score,
            "source_false_positive_rate": self.source_false_positive_rate,
            "overall_score": self.overall_score(),
            "metadata": dict(self.metadata),
        }


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


__all__ = ["MemoryEvaluationMetrics", "MemoryMetric"]
