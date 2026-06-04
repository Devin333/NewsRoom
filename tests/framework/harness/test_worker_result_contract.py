from __future__ import annotations

import pytest

from framework.harness import HarnessValidationError, HarnessWorkerResult


@pytest.mark.parametrize(
    "forbidden_key",
    [
        "next_step",
        "quality_passed",
        "write_memory",
        "accept",
        "publish",
        "promote_skill",
        "skip_eval",
    ],
)
def test_worker_result_rejects_flow_control_fields(forbidden_key: str) -> None:
    with pytest.raises(HarnessValidationError):
        HarnessWorkerResult(status="succeeded", output={forbidden_key: True})


def test_worker_result_exposes_candidate_data_only() -> None:
    result = HarnessWorkerResult(
        status="succeeded",
        output={"candidate_summary": "A grounded candidate."},
        artifacts=("artifact://candidate",),
        diagnostics={"warnings": []},
        metrics={"tokens": 12},
    )

    assert result.to_dict() == {
        "status": "succeeded",
        "output": {"candidate_summary": "A grounded candidate."},
        "artifacts": ["artifact://candidate"],
        "diagnostics": {"warnings": []},
        "metrics": {"tokens": 12},
        "error": None,
    }
