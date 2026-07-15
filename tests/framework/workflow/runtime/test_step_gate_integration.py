from __future__ import annotations

from pathlib import Path
from typing import Any

from framework.specs import StepSpec, StepStatus, StepType, WorkflowSpec
from framework.artifacts import ArtifactReference
from framework.workflow.runners.base import StepRunnerCapability, StepRunnerSideEffectLevel
from framework.workflow.runners.registry import StepRunnerRegistry
from framework.artifacts import ArtifactManager
from framework.events import EventRuntime, default_event_schema_catalog
from framework.workflow.runtime.executor import WorkflowExecutor
from framework.workflow.runtime.result import StepOutcome
from infrastructure.storage.events.sqlite import SQLiteEventStore


class _Runner:
    capability = StepRunnerCapability(
        step_type=StepType.FUNCTION,
        runner_id="gate-test",
        version="1.0",
        supports_checkpoint=True,
        supports_resume=True,
        supports_timeout=True,
        supports_retry=True,
        side_effect_level=StepRunnerSideEffectLevel.NONE,
    )

    def __init__(self, outcome: StepOutcome) -> None:
        self._outcome = outcome

    def can_resolve(self, step: StepSpec) -> bool:
        return step.step_type == StepType.FUNCTION

    def validate_step(self, step: StepSpec) -> list[Any]:
        return []

    def run(self, step: StepSpec, buffer: Any) -> StepOutcome:
        return self._outcome


def _executor(tmp_path: Path, outcome: StepOutcome) -> WorkflowExecutor:
    registry = StepRunnerRegistry()
    registry.register(StepType.FUNCTION, _Runner(outcome))
    event_store = SQLiteEventStore(tmp_path / "events.sqlite3")
    event_catalog = default_event_schema_catalog()
    return WorkflowExecutor(
        function_step_runner=None,
        artifact_manager=ArtifactManager(tmp_path),
        step_runner_registry=registry,
        event_runtime=EventRuntime(store=event_store, schema_catalog=event_catalog),
        event_reader=event_store,
        event_schema_catalog=event_catalog,
    )


def test_successful_step_writes_gate_result_and_manifest_summary(tmp_path: Path) -> None:
    step = StepSpec(step_id="s1", write_keys=["ok"])
    workflow = WorkflowSpec(
        workflow_id="wf-gate",
        name="Workflow",
        version="1.0",
        steps=[step],
        terminal_step_ids=["s1"],
    )

    result = _executor(tmp_path, StepOutcome(status=StepStatus.SUCCEEDED, outputs={"ok": True})).execute(
        workflow,
        {},
        profile="test",
        run_id="run-gate-ok",
    )

    outcome = result.step_results["s1"]
    assert outcome.gate_result["decision"] == "pass"
    assert result.manifest["step_outcome_summary"]["s1"]["gate_result"]["decision"] == "pass"
    assert result.manifest["gate_summary"][0]["step_id"] == "s1"


def test_missing_eval_output_blocks_step(tmp_path: Path) -> None:
    step = StepSpec(
        step_id="s1",
        write_keys=["ok"],
        runtime_quality={
            "evaluation": {"enabled": True, "required_output_keys": ["ok"]},
            "gate": {"dimensions": ["correctness"]},
        },
    )
    workflow = WorkflowSpec(
        workflow_id="wf-gate-block",
        name="Workflow",
        version="1.0",
        steps=[step],
        terminal_step_ids=["s1"],
    )

    result = _executor(tmp_path, StepOutcome(status=StepStatus.SUCCEEDED, outputs={})).execute(
        workflow,
        {},
        profile="test",
        run_id="run-gate-block",
    )

    outcome = result.step_results["s1"]
    assert outcome.status == StepStatus.BLOCKED
    assert outcome.error_type == "WorkflowGateBlocked"
    assert outcome.gate_result["decision"] == "block"
    assert result.gate_result["decision"] == "block"


def test_warn_only_gate_does_not_block(tmp_path: Path) -> None:
    step = StepSpec(
        step_id="s1",
        write_keys=["ok"],
        runtime_quality={
            "evaluation": {"enabled": True, "required_output_keys": ["ok"]},
            "gate": {"mode": "warn_only", "dimensions": ["correctness"]},
        },
    )
    workflow = WorkflowSpec(
        workflow_id="wf-gate-warn",
        name="Workflow",
        version="1.0",
        steps=[step],
        terminal_step_ids=["s1"],
    )

    result = _executor(tmp_path, StepOutcome(status=StepStatus.SUCCEEDED, outputs={})).execute(
        workflow,
        {},
        profile="test",
        run_id="run-gate-warn",
    )

    outcome = result.step_results["s1"]
    assert outcome.status == StepStatus.SUCCEEDED
    assert outcome.gate_result["decision"] == "warn"
    assert outcome.warnings


def test_artifact_gate_accepts_artifact_reference_kind(tmp_path: Path) -> None:
    step = StepSpec(
        step_id="s1",
        write_keys=["ok"],
        runtime_quality={
            "evaluation": {"enabled": True, "required_artifact_kinds": ["metrics"]},
            "gate": {"dimensions": ["artifact"]},
        },
    )
    workflow = WorkflowSpec(
        workflow_id="wf-gate-artifact-kind",
        name="Workflow",
        version="1.0",
        steps=[step],
        terminal_step_ids=["s1"],
    )

    result = _executor(
        tmp_path,
        StepOutcome(
            status=StepStatus.SUCCEEDED,
            outputs={"ok": True},
            artifact_refs=[
                ArtifactReference(
                    artifact_id="metrics",
                    run_id="run-gate-artifact-kind",
                    kind="metrics",
                    uri="metrics.json",
                )
            ],
        ),
    ).execute(
        workflow,
        {},
        profile="test",
        run_id="run-gate-artifact-kind",
    )

    outcome = result.step_results["s1"]
    assert outcome.status == StepStatus.SUCCEEDED
    assert outcome.gate_result["decision"] == "pass"
