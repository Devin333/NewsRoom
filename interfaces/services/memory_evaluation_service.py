from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.memory.evaluation import MemoryEvaluationRequest, MemoryEvaluator


@dataclass(frozen=True)
class MemoryEvaluationApplicationResult:
    report: Any

    def to_dict(self) -> dict[str, Any]:
        return self.report.to_dict()


class MemoryEvaluationApplicationService:
    def __init__(self, evaluator: MemoryEvaluator) -> None:
        self.evaluator = evaluator

    def evaluate_topic(self, topic: str, *, limit: int = 100) -> MemoryEvaluationApplicationResult:
        return MemoryEvaluationApplicationResult(
            self.evaluator.evaluate(MemoryEvaluationRequest(topic=topic, limit=limit))
        )

    def evaluate_entity(self, entity_id: str, *, limit: int = 100) -> MemoryEvaluationApplicationResult:
        return MemoryEvaluationApplicationResult(
            self.evaluator.evaluate(MemoryEvaluationRequest(entity_id=entity_id, limit=limit))
        )


__all__ = ["MemoryEvaluationApplicationResult", "MemoryEvaluationApplicationService"]
