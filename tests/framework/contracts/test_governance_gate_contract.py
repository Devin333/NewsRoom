from __future__ import annotations

import json

from framework.governance import CompositeAndGate, GateCheckResult, GateResult


def test_governance_gate_contract_pass_warn_block_round_trip() -> None:
    passed = CompositeAndGate("gate-pass").evaluate(
        [GateCheckResult(check_id="compat", dimension="compatibility", passed=True)]
    )
    warned = CompositeAndGate("gate-warn", mode="warn_only").evaluate(
        [
            GateCheckResult(
                check_id="quality",
                dimension="correctness",
                passed=False,
                severity="error",
                reason="missing output",
            )
        ]
    )
    blocked = CompositeAndGate("gate-block").evaluate(
        [
            GateCheckResult(
                check_id="safety",
                dimension="safety",
                passed=False,
                severity="critical",
                reason="unsafe",
            )
        ]
    )

    assert passed.decision == "pass"
    assert warned.decision == "warn"
    assert warned.passed is True
    assert blocked.decision == "block"
    assert blocked.passed is False
    assert blocked.failed_dimensions == ["safety"]
    assert GateResult.from_dict(blocked.to_dict()).decision == "block"
    json.dumps(blocked.to_dict())
