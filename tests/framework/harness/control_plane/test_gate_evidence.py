from __future__ import annotations

import pytest

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.gates import HarnessGateResult
from framework.harness.quality.verdict import HarnessQualityVerdict, aggregate_gate_verdict


def test_gate_result_requires_boolean_outcome() -> None:
    with pytest.raises(HarnessValidationError, match="boolean"):
        HarnessGateResult(gate_name="schema", passed="true")  # type: ignore[arg-type]


def test_gate_result_evidence_preserves_safe_payload_shape() -> None:
    result = HarnessGateResult(
        gate_name="schema",
        passed=False,
        reason="missing title",
        details={"missing": ["title"]},
    ).with_evidence(
        gate_reference="schema@1",
        input_ref="sha256:" + "1" * 64,
        reason_code="gate_failed",
    )

    payload = result.to_dict()
    assert set(payload) == {"gate", "passed", "reason", "details"}
    assert payload["details"]["harness_gate"] == {
        "reference": "schema@1",
        "input_ref": "sha256:" + "1" * 64,
        "result_ref": payload["details"]["harness_gate"]["result_ref"],
        "reason_code": "gate_failed",
    }
    assert payload["details"]["harness_gate"]["result_ref"].startswith("sha256:")


def test_verdict_is_aggregated_from_gate_results_only() -> None:
    results = (
        HarnessGateResult(
            gate_name="schema",
            passed=True,
            details={"score": 0.95},
        ).with_evidence(
            gate_reference="schema@1",
            input_ref="sha256:" + "2" * 64,
            reason_code="gate_passed",
        ),
        HarnessGateResult(
            gate_name="evidence",
            passed=False,
            reason="claim is unsupported",
            details={"score": 0.4, "repair_hints": ["add a citation"]},
        ).with_evidence(
            gate_reference="evidence@2",
            input_ref="sha256:" + "3" * 64,
            reason_code="gate_failed",
        ),
    )

    verdict = aggregate_gate_verdict(results, declared_gate_reference="evidence@2")

    assert verdict is not None
    assert verdict.passed is False
    assert verdict.score == 0.4
    assert verdict.issues == ("claim is unsupported",)
    assert verdict.repair_hints == ("add a citation",)
    assert verdict.metadata["declared_gate_reference"] == "evidence@2"
    assert verdict.metadata["gate_references"] == ["schema@1", "evidence@2"]


def test_no_declared_gate_produces_no_routable_verdict() -> None:
    result = HarnessGateResult(gate_name="schema", passed=True)

    assert aggregate_gate_verdict((result,), declared_gate_reference=None) is None


@pytest.mark.parametrize(
    "kwargs",
    (
        {"passed": "false"},
        {"passed": True, "score": True},
        {"passed": True, "issues": "not-a-sequence"},
        {"passed": True, "repair_hints": "not-a-sequence"},
        {"passed": True, "metadata": "not-an-object"},
    ),
)
def test_quality_verdict_rejects_malformed_wire_types(kwargs) -> None:
    with pytest.raises(HarnessValidationError):
        HarnessQualityVerdict(**kwargs)
