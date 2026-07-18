from __future__ import annotations

import pytest

from framework.harness import (
    FORBIDDEN_WORKER_RESULT_KEYS,
    HarnessValidationError,
    HarnessWorkerResult,
)


@pytest.mark.parametrize(
    "forbidden_key",
    sorted(FORBIDDEN_WORKER_RESULT_KEYS),
)
def test_worker_result_rejects_flow_control_fields(forbidden_key: str) -> None:
    with pytest.raises(HarnessValidationError) as captured:
        HarnessWorkerResult(status="succeeded", output={forbidden_key: True})

    assert captured.value.details["forbidden"] == [forbidden_key]


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


def test_worker_result_allows_observations_and_completed_domain_facts() -> None:
    result = HarnessWorkerResult(
        status="succeeded",
        output={
            "quality_observation": {"score": 0.9},
            "authorization_observation": {"requested_tools": ["search"]},
            "memory_write_candidate": {"namespace": "research.private"},
            "published": True,
        },
    )

    assert result.output["quality_observation"] == {"score": 0.9}
