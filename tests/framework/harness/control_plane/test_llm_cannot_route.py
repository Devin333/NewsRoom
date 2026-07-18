from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from framework.harness import (
    HarnessControlPlane,
    HarnessRunSpec,
    HarnessStepSpec,
    HarnessValidationError,
    HarnessWorkerResult,
    HarnessWorkflowSpec,
    InMemoryHarnessEventPort,
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


def test_fake_llm_next_step_output_is_rejected_at_worker_ingress() -> None:
    workflow = HarnessWorkflowSpec(
        workflow_id="llm-route",
        steps=(
            HarnessStepSpec(step_id="draft", worker_type="llm", output_key="draft"),
            HarnessStepSpec(step_id="review", worker_type="llm", output_key="review"),
            HarnessStepSpec(step_id="publish", worker_type="artifact", output_key="published"),
        ),
        entry_step_id="draft",
    )
    event_port = InMemoryHarnessEventPort()
    downstream_calls: list[str] = []
    control_plane = HarnessControlPlane(
        event_port=event_port,
        worker_registry={
            "draft": lambda task: LeakyWorkerResult(
                status=HarnessWorkerStatus.SUCCEEDED,
                output={"next_step": "publish", "body": "candidate text"},
            ),
            "review": lambda task: downstream_calls.append("review"),
            "publish": lambda task: downstream_calls.append("publish"),
        }
    )

    with pytest.raises(HarnessValidationError) as captured:
        control_plane.run(HarnessRunSpec(run_id="run-llm-route", workflow=workflow))

    assert captured.value.details["forbidden"] == ["next_step"]
    assert downstream_calls == []
    assert not any(
        event.event_type.value == "worker_result_recorded"
        for event in event_port.events
    )


@pytest.mark.parametrize("forbidden_key", ("next_step", "write_memory", "publish"))
def test_mutated_worker_result_is_revalidated_at_ingress(forbidden_key: str) -> None:
    worker_result = HarnessWorkerResult(
        status="succeeded",
        output={"candidate": "safe at construction"},
    )
    worker_result.output[forbidden_key] = True
    event_port = InMemoryHarnessEventPort()
    workflow = HarnessWorkflowSpec(
        workflow_id="mutated-worker-result",
        steps=(HarnessStepSpec(step_id="draft", worker_type="llm"),),
        entry_step_id="draft",
    )

    with pytest.raises(HarnessValidationError) as captured:
        HarnessControlPlane(
            event_port=event_port,
            worker_registry={"draft": lambda task: worker_result},
        ).run(
            HarnessRunSpec(
                run_id=f"run-mutated-worker-{forbidden_key}",
                workflow=workflow,
            )
        )

    assert captured.value.details["forbidden"] == [forbidden_key]
    assert not any(
        event.event_type.value == "worker_result_recorded"
        for event in event_port.events
    )
