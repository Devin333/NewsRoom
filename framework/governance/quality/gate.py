from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.governance.quality.evaluator import QualityEvaluator
from framework.governance.quality.rule import QualityRule
from framework.governance.quality.verdict import QualityDecision, QualityVerdict
from framework.shared.errors import RuntimeExecutionError


class QualityGateError(RuntimeExecutionError):
    def __init__(self, verdict: QualityVerdict) -> None:
        super().__init__(
            verdict.reason or "quality gate failed",
            code="quality_gate_failed",
            details={"verdict": verdict.to_dict()},
        )
        self.verdict = verdict


@dataclass
class QualityGate:
    rules: list[QualityRule] = field(default_factory=list)
    evaluator: QualityEvaluator = field(default_factory=QualityEvaluator)

    def check(self, payload: Any) -> QualityVerdict:
        return self.evaluator.evaluate(payload, self.rules)

    def require_pass(self, payload: Any) -> None:
        verdict = self.check(payload)
        if verdict.decision == QualityDecision.FAIL:
            raise QualityGateError(verdict)
