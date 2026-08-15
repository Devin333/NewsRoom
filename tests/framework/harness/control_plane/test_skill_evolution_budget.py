from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from framework.harness import (
    HarnessBudget,
    HarnessControlPlane,
    HarnessRunSpec,
    HarnessRunStatus,
    HarnessStepSpec,
    HarnessValidationError,
    HarnessWorkerResult,
    HarnessWorkerStatus,
    HarnessWorkerType,
    InMemoryHarnessEventPort,
)
from framework.harness.workflow.spec import HarnessWorkflowSpec


@dataclass(frozen=True)
class LeakySkillOptimizerResult:
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


def test_worker_result_contract_rejects_skill_promotion_fields() -> None:
    with pytest.raises(HarnessValidationError):
        HarnessWorkerResult(status="succeeded", output={"promote_skill": True})

    with pytest.raises(HarnessValidationError):
        HarnessWorkerResult(status="succeeded", output={"active": True})


def test_fake_skill_optimizer_promotion_aliases_are_rejected_before_publish() -> None:
    workflow = HarnessWorkflowSpec(
        workflow_id="skill-no-publish",
        steps=(
            HarnessStepSpec(
                step_id="optimize",
                worker_type=HarnessWorkerType.SKILL_EVOLUTION,
                output_key="candidate",
            ),
        ),
        entry_step_id="optimize",
    )
    control_plane = HarnessControlPlane(
        event_port=InMemoryHarnessEventPort(),
        worker_registry={
            "optimize": lambda task: LeakySkillOptimizerResult(
                status=HarnessWorkerStatus.SUCCEEDED,
                output={
                    "promote": True,
                    "release": True,
                    "candidate_count": 1,
                    "patch_operations": 1,
                    "eval_cases": 1,
                    "sandbox_runs": 1,
                },
            )
        }
    )

    with pytest.raises(HarnessValidationError) as captured:
        control_plane.run(
            HarnessRunSpec(
            run_id="run-skill-no-publish",
            workflow=workflow,
            budget=HarnessBudget(
                max_turns=10,
                max_replans=0,
                max_retries_per_step=0,
                max_worker_calls=5,
                max_evolution_epochs=1,
                max_candidates_per_run=1,
                max_patch_operations=1,
                max_eval_cases=1,
                max_sandbox_runs=1,
            ),
            )
        )

    assert captured.value.code == "worker_decision_field_rejected"
    assert captured.value.details["forbidden_paths"] == ["output.promote", "output.release"]


def test_skill_evolution_budget_exhaustion_halts_run() -> None:
    workflow = HarnessWorkflowSpec(
        workflow_id="skill-budget",
        steps=(
            HarnessStepSpec(
                step_id="optimize",
                worker_type=HarnessWorkerType.SKILL_EVOLUTION,
                output_key="candidate",
            ),
        ),
        entry_step_id="optimize",
    )
    result = HarnessControlPlane(
        event_port=InMemoryHarnessEventPort(),
        worker_registry={
            "optimize": lambda task: HarnessWorkerResult(
                status="succeeded",
                output={"candidate_count": 2, "patch_operations": 1, "eval_cases": 1, "sandbox_runs": 1},
            )
        }
    ).run(
        HarnessRunSpec(
            run_id="run-skill-budget",
            workflow=workflow,
            budget=HarnessBudget(
                max_turns=10,
                max_replans=0,
                max_retries_per_step=0,
                max_worker_calls=5,
                max_evolution_epochs=1,
                max_candidates_per_run=1,
                max_patch_operations=1,
                max_eval_cases=1,
                max_sandbox_runs=1,
            ),
        )
    )

    assert result.state.status == HarnessRunStatus.HALTED
    assert result.state.metadata["terminal_reason"] == "verification failed and replan budget is exhausted"
    gate_events = [event for event in result.events if event.payload.get("gate") == "skill_evolution_budget"]
    assert gate_events[-1].payload["passed"] is False
