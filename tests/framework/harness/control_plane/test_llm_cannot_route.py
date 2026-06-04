from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from framework.harness import (
    HarnessControlPlane,
    HarnessDecisionType,
    HarnessRunSpec,
    HarnessRunStatus,
    HarnessStepSpec,
    HarnessValidationError,
    HarnessWorkerResult,
    HarnessWorkflowSpec,
)
from framework.harness.workers.result import HarnessWorkerStatus


@dataclass(frozen=True)
class LeakyWorkerResult:
    status: HarnessWorkerStatus
    output: dict[str, Any]
    artifacts: tuple[str, ...] = ()
    diagnostics: dict[str, Any] | None = None
    metrics: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "output": self.output,
            "artifacts": list(self.artifacts),
            "diagnostics": self.diagnostics or {},
            "metrics": self.metrics or {},
            "error": self.error,
        }


def test_worker_result_contract_rejects_next_step_field() -> None:
    with pytest.raises(HarnessValidationError):
        HarnessWorkerResult(status="succeeded", output={"next_step": "publish"})


def test_fake_llm_next_step_output_does_not_control_routing() -> None:
    workflow = HarnessWorkflowSpec(
        workflow_id="llm-route",
        steps=(
            HarnessStepSpec(step_id="draft", worker_type="llm", output_key="draft"),
            HarnessStepSpec(step_id="review", worker_type="llm", output_key="review"),
            HarnessStepSpec(step_id="publish", worker_type="artifact", output_key="published"),
        ),
        entry_step_id="draft",
    )
    result = HarnessControlPlane(
        worker_registry={
            "draft": lambda task: LeakyWorkerResult(
                status=HarnessWorkerStatus.SUCCEEDED,
                output={"next_step": "publish", "body": "candidate text"},
            ),
            "review": lambda task: HarnessWorkerResult(status="succeeded", output={"reviewed": True}),
            "publish": lambda task: HarnessWorkerResult(status="succeeded", output={"published": True}),
        }
    ).run(HarnessRunSpec(run_id="run-llm-route", workflow=workflow))

    route_decisions = [decision for decision in result.decisions if decision.decision_type == HarnessDecisionType.ROUTE_TO_STEP]
    assert route_decisions[0].target_step_id == "review"
    assert result.state.status == HarnessRunStatus.SUCCEEDED
    assert "publish" in result.worker_results
