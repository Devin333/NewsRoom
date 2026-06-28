from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.rag.evaluation.failure_reason import RAGFailureReason, normalize_failure_reason
from framework.shared.json import to_jsonable


@dataclass(frozen=True)
class MetricValue:
    name: str
    value: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.name).strip():
            raise ValueError("metric name is required")
        object.__setattr__(self, "name", str(self.name))
        object.__setattr__(self, "value", float(self.value))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "metadata": to_jsonable(self.metadata),
        }


@dataclass(frozen=True)
class RAGScorecard:
    run_id: str
    metrics: tuple[MetricValue, ...] = ()
    failure_reasons: tuple[RAGFailureReason | str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.run_id).strip():
            raise ValueError("run_id is required")
        object.__setattr__(self, "run_id", str(self.run_id))
        object.__setattr__(self, "metrics", tuple(self.metrics))
        object.__setattr__(
            self,
            "failure_reasons",
            tuple(normalize_failure_reason(reason) for reason in self.failure_reasons),
        )
        object.__setattr__(self, "metadata", dict(self.metadata))

    def metric(self, name: str) -> MetricValue | None:
        for metric in self.metrics:
            if metric.name == name:
                return metric
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "metrics": [metric.to_dict() for metric in self.metrics],
            "failure_reasons": [reason.value for reason in self.failure_reasons],
            "metadata": to_jsonable(self.metadata),
        }


@dataclass(frozen=True)
class RAGEvaluationReport:
    title: str
    scorecard: RAGScorecard

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "scorecard": self.scorecard.to_dict(),
        }

    def to_markdown(self) -> str:
        lines = [f"# {self.title}", "", f"- run_id: `{self.scorecard.run_id}`"]
        if self.scorecard.metrics:
            lines.extend(["", "## Metrics"])
            for metric in self.scorecard.metrics:
                lines.append(f"- {metric.name}: `{metric.value:.3f}`")
        if self.scorecard.failure_reasons:
            lines.extend(["", "## Failure Reasons"])
            for reason in self.scorecard.failure_reasons:
                lines.append(f"- {reason.value}")
        return "\n".join(lines)


__all__ = ["MetricValue", "RAGEvaluationReport", "RAGScorecard"]
