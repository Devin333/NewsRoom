from __future__ import annotations

import pytest

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.graph.observability import (
    HarnessGraphHealthReport,
    HarnessGraphMetricSample,
    HarnessGraphOperatorDiagnostic,
)


def test_metric_sample_normalizes_low_cardinality_labels() -> None:
    sample = HarnessGraphMetricSample(
        "harness_graph_ready_nodes",
        2,
        {"outcome": "succeeded", "lifecycle": "completed"},
    )

    assert sample.value == 2.0
    assert sample.to_dict() == {
        "name": "harness_graph_ready_nodes",
        "value": 2.0,
        "labels": {"lifecycle": "completed", "outcome": "succeeded"},
    }
    with pytest.raises(TypeError):
        sample.labels["result"] = "mutated"  # type: ignore[index]

    with pytest.raises(HarnessValidationError) as captured:
        HarnessGraphMetricSample("harness_graph_ready_nodes", 2, {"run_id": "run-1"})

    assert captured.value.code == "graph_metric_label_rejected"


def test_operator_diagnostic_exposes_checksum_evidence_only() -> None:
    first = _checksum("first")
    second = _checksum("second")
    diagnostic = HarnessGraphOperatorDiagnostic(
        "projection_lag",
        "warning",
        evidence_refs=(second, first),
        current_value=101,
        threshold=100,
    )

    assert diagnostic.to_dict()["evidence_refs"] == [first, second]

    with pytest.raises(HarnessValidationError) as captured:
        HarnessGraphOperatorDiagnostic(
            "projection_lag",
            "warning",
            evidence_refs=("raw-payload-ref",),
        )

    assert captured.value.code == "graph_diagnostic_reference_rejected"


def test_health_report_sorts_diagnostics_and_rejects_other_values() -> None:
    report = HarnessGraphHealthReport(
        "unhealthy",
        (
            HarnessGraphOperatorDiagnostic("stuck_wait", "warning"),
            HarnessGraphOperatorDiagnostic("compensation_failure", "error"),
        ),
        17,
    )

    assert report.status.value == "unhealthy"
    assert [item.code for item in report.diagnostics] == [
        "compensation_failure",
        "stuck_wait",
    ]

    with pytest.raises(TypeError, match="HarnessGraphOperatorDiagnostic"):
        HarnessGraphHealthReport("healthy", ("not-a-diagnostic",), 17)  # type: ignore[arg-type]


def _checksum(seed: str) -> str:
    return f"sha256:{seed.encode().hex().ljust(64, '0')[:64]}"
