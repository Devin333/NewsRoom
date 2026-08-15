from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from framework.harness import (
    HarnessControlPlane,
    HarnessRunSpec,
    HarnessStepSpec,
    HarnessValidationError,
    HarnessWorkerEvidence,
    HarnessWorkerResult,
    InMemoryHarnessEventPort,
)
from framework.harness.workflow.spec import HarnessWorkflowSpec
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


@pytest.mark.parametrize(
    ("forbidden_key", "forbidden_value"),
    (("next_step", "publish"), ("quality_score", 0.99)),
)
def test_fake_llm_control_output_is_rejected_at_worker_ingress(
    forbidden_key: str,
    forbidden_value: object,
) -> None:
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
                output={forbidden_key: forbidden_value, "body": "candidate text"},
            ),
            "review": lambda task: downstream_calls.append("review"),
            "publish": lambda task: downstream_calls.append("publish"),
        }
    )

    with pytest.raises(HarnessValidationError) as captured:
        control_plane.run(
            HarnessRunSpec(
                run_id=f"run-llm-forbidden-{forbidden_key}",
                workflow=workflow,
            )
        )

    assert captured.value.details["forbidden"] == [forbidden_key]
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


def test_worker_ingress_preserves_typed_evidence_and_candidate_refs() -> None:
    evidence = HarnessWorkerEvidence(
        evidence_type="llm_candidate",
        payload={"response_ref": "artifact://run-worker-evidence/response"},
    )
    candidate = HarnessWorkerResult(
        status="succeeded",
        output={"candidate": "bounded"},
        artifacts=("artifact://run-worker-evidence/response",),
        evidence=(evidence,),
    )
    result = HarnessControlPlane(
        event_port=InMemoryHarnessEventPort(),
        worker_registry={"draft": lambda task: candidate},
    ).run(
        HarnessRunSpec(
            run_id="run-worker-evidence",
            workflow=HarnessWorkflowSpec(
                workflow_id="worker-evidence",
                steps=(HarnessStepSpec(step_id="draft", worker_type="llm"),),
                entry_step_id="draft",
            ),
        )
    )

    accepted = result.worker_results["draft"]
    assert accepted.evidence == (evidence,)
    assert accepted.artifacts == ("artifact://run-worker-evidence/response",)


def test_worker_ingress_rejects_top_level_control_field() -> None:
    class TopLevelLeakyResult:
        def to_dict(self) -> dict[str, Any]:
            return {
                **HarnessWorkerResult(status="succeeded").to_dict(),
                "next_route": "publish",
            }

    event_port = InMemoryHarnessEventPort()
    with pytest.raises(HarnessValidationError) as captured:
        HarnessControlPlane(
            event_port=event_port,
            worker_registry={"draft": lambda task: TopLevelLeakyResult()},
        ).run(
            HarnessRunSpec(
                run_id="run-top-level-control-field",
                workflow=HarnessWorkflowSpec(
                    workflow_id="top-level-control-field",
                    steps=(HarnessStepSpec(step_id="draft", worker_type="llm"),),
                    entry_step_id="draft",
                ),
            )
        )

    assert captured.value.code == "worker_decision_field_rejected"
    assert captured.value.details["forbidden_paths"] == ["next_route"]
    assert not any(
        event.event_type.value == "worker_result_recorded"
        for event in event_port.events
    )
