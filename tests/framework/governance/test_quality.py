from __future__ import annotations

import pytest

from framework.governance.quality import (
    QualityDecision,
    QualityEvaluator,
    QualityGate,
    QualityGateError,
    QualityVerdict,
)


class StaticRule:
    def __init__(self, verdict: QualityVerdict) -> None:
        self.verdict = verdict

    def evaluate(self, payload: object) -> QualityVerdict:
        return self.verdict


def test_quality_verdict_serializes() -> None:
    verdict = QualityVerdict.failed(score=0.2, reason="too risky", findings=["risk"])

    assert verdict.to_dict() == {
        "decision": "fail",
        "score": 0.2,
        "reason": "too risky",
        "findings": ["risk"],
        "metadata": {},
    }


def test_quality_evaluator_combines_rule_results() -> None:
    evaluator = QualityEvaluator()

    verdict = evaluator.evaluate(
        {},
        [
            StaticRule(QualityVerdict.passed(score=1.0, reason="ok")),
            StaticRule(QualityVerdict.warned(score=0.5, reason="watch", findings=["warn"])),
        ],
    )

    assert verdict.decision == QualityDecision.WARN
    assert verdict.score == 0.75
    assert verdict.findings == ["warn"]


def test_quality_gate_raises_on_failed_verdict() -> None:
    gate = QualityGate([StaticRule(QualityVerdict.failed(reason="blocked"))])

    with pytest.raises(QualityGateError) as exc:
        gate.require_pass({})

    assert exc.value.verdict.decision == QualityDecision.FAIL
