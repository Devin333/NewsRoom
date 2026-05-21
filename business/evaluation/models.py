from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EvaluationMetricResult:
    metric_name: str
    score: float
    passed: bool
    threshold: float | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metric_name", str(self.metric_name))
        object.__setattr__(self, "score", clamp_metric(self.score))
        if self.threshold is not None:
            object.__setattr__(self, "threshold", clamp_metric(self.threshold))
        object.__setattr__(self, "details", dict(self.details or {}))

    @classmethod
    def create(
        cls,
        metric_name: str,
        score: float,
        *,
        threshold: float | None = None,
        details: dict[str, Any] | None = None,
    ) -> "EvaluationMetricResult":
        actual_score = clamp_metric(score)
        return cls(
            metric_name=metric_name,
            score=actual_score,
            threshold=threshold,
            passed=True if threshold is None else actual_score >= threshold,
            details=details or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_name": self.metric_name,
            "score": self.score,
            "passed": self.passed,
            "threshold": self.threshold,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class BusinessEvaluationResult:
    subject_id: str
    subject_type: str
    metrics: list[EvaluationMetricResult] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject_id", str(self.subject_id))
        object.__setattr__(self, "subject_type", str(self.subject_type))
        object.__setattr__(
            self,
            "metrics",
            [
                metric
                if isinstance(metric, EvaluationMetricResult)
                else EvaluationMetricResult(**dict(metric))
                for metric in self.metrics
            ],
        )
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    @property
    def score(self) -> float:
        if not self.metrics:
            return 0.0
        return clamp_metric(sum(metric.score for metric in self.metrics) / len(self.metrics))

    @property
    def passed(self) -> bool:
        return all(metric.passed for metric in self.metrics)

    def metric(self, name: str) -> EvaluationMetricResult | None:
        return next((metric for metric in self.metrics if metric.metric_name == name), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject_id": self.subject_id,
            "subject_type": self.subject_type,
            "score": self.score,
            "passed": self.passed,
            "metrics": [metric.to_dict() for metric in self.metrics],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class RankingEvaluationCase:
    expected_ids: list[str]
    actual_ids: list[str]
    relevance: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "expected_ids", [str(item) for item in self.expected_ids])
        object.__setattr__(self, "actual_ids", [str(item) for item in self.actual_ids])
        object.__setattr__(
            self,
            "relevance",
            {str(key): clamp_metric(value) for key, value in dict(self.relevance or {}).items()},
        )


def clamp_metric(value: float) -> float:
    numeric = float(value)
    if numeric < 0.0:
        return 0.0
    if numeric > 1.0:
        return 1.0
    return round(numeric, 4)
