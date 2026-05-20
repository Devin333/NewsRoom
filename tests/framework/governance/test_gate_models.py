from __future__ import annotations

from framework.governance import CompositeAndGate, GateCheckResult, GateResult, PolicyDecision


def test_gate_result_round_trip() -> None:
    result = CompositeAndGate("gate-1").evaluate(
        [
            GateCheckResult("compat", "compatibility", True),
            GateCheckResult("safety", "safety", False, reason="blocked"),
        ]
    )
    restored = GateResult.from_dict(result.to_dict())

    assert restored.passed is False
    assert restored.decision == "block"
    assert restored.failed_dimensions == ["safety"]


def test_warn_only_gate_allows_with_warning_decision() -> None:
    result = CompositeAndGate("gate-1", mode="warn_only").evaluate(
        [GateCheckResult("safety", "safety", False, reason="warn")]
    )

    assert result.passed is True
    assert result.decision == "warn"


def test_policy_decision_round_trip() -> None:
    decision = PolicyDecision.block(
        "memory.write",
        reason="invalid namespace",
        risk_level="high",
        metadata={"namespace": "../x"},
    )
    restored = PolicyDecision.from_dict(decision.to_dict())

    assert restored.allowed is False
    assert restored.decision == "block"
    assert restored.metadata["namespace"] == "../x"
