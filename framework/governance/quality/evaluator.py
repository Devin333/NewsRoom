from __future__ import annotations

from typing import Any, Iterable

from framework.governance.quality.rule import QualityRule
from framework.governance.quality.verdict import QualityDecision, QualityVerdict


class QualityEvaluator:
    def evaluate(self, payload: Any, rules: Iterable[QualityRule]) -> QualityVerdict:
        verdicts = [rule.evaluate(payload) for rule in rules]
        if not verdicts:
            return QualityVerdict.passed(reason="no quality rules configured")

        findings: list[str] = []
        metadata: dict[str, Any] = {"rule_count": len(verdicts)}
        scores = [verdict.score for verdict in verdicts if verdict.score is not None]
        reasons = [verdict.reason for verdict in verdicts if verdict.reason]
        for verdict in verdicts:
            findings.extend(verdict.findings)

        if any(verdict.decision == QualityDecision.FAIL for verdict in verdicts):
            decision = QualityDecision.FAIL
        elif any(verdict.decision == QualityDecision.WARN for verdict in verdicts):
            decision = QualityDecision.WARN
        else:
            decision = QualityDecision.PASS

        return QualityVerdict(
            decision=decision,
            score=sum(scores) / len(scores) if scores else None,
            reason="; ".join(reasons) if reasons else None,
            findings=findings,
            metadata=metadata,
        )
