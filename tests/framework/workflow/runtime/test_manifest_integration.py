from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from framework.specs import StepSpec, StepStatus, StepType, WorkflowSpec
from framework.workflow.runners.base import StepRunnerCapability, StepRunnerSideEffectLevel
from framework.workflow.runners.registry import StepRunnerRegistry
import pytest

from framework.artifacts import ArtifactManager, ArtifactPathError
from framework.events import EventRuntime, default_event_schema_catalog
from framework.workflow.runtime.executor import WorkflowExecutor
from framework.workflow.runtime.manifest import validate_run_manifest
from framework.workflow.runtime.result import StepOutcome
from infrastructure.storage.events.sqlite import SQLiteEventStore


class _Runner:
    capability = StepRunnerCapability(
        step_type=StepType.FUNCTION,
        runner_id="manifest-test",
        version="1.0",
        supports_checkpoint=True,
        supports_resume=True,
        supports_timeout=True,
        supports_retry=True,
        side_effect_level=StepRunnerSideEffectLevel.NONE,
    )

    def can_resolve(self, step: StepSpec) -> bool:
        return step.step_type == StepType.FUNCTION

    def validate_step(self, step: StepSpec) -> list[Any]:
        return []

    def run(self, step: StepSpec, buffer: Any) -> StepOutcome:
        return StepOutcome(status=StepStatus.SUCCEEDED, outputs={"ok": True})


def test_workflow_manifest_contains_q05_run_evidence(tmp_path) -> None:
    registry = StepRunnerRegistry()
    registry.register(StepType.FUNCTION, _Runner())
    workflow = WorkflowSpec(
        workflow_id="wf-manifest",
        name="Workflow",
        version="1.0",
        steps=[StepSpec(step_id="s1", write_keys=["ok"])],
        terminal_step_ids=["s1"],
    )
    event_store = SQLiteEventStore(tmp_path / "events.sqlite3")
    event_catalog = default_event_schema_catalog()

    result = WorkflowExecutor(
        function_step_runner=None,
        artifact_manager=ArtifactManager(tmp_path),
        step_runner_registry=registry,
        event_runtime=EventRuntime(store=event_store, schema_catalog=event_catalog),
        event_reader=event_store,
        event_schema_catalog=event_catalog,
    ).execute(workflow, {}, profile="test", run_id="run-manifest")

    manifest_path = tmp_path / "run-manifest" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["run_id"] == "run-manifest"
    assert manifest["status"] == "succeeded"
    assert manifest["started_at"]
    assert manifest["completed_at"] == manifest["finished_at"]
    assert manifest["trace_ref"] == "events.jsonl"
    assert manifest["gate_result_ref"] == "gate_result.json"
    assert manifest["run_history_ref"] == "run_history.jsonl"
    assert manifest["step_summaries"][0]["step_id"] == "s1"
    assert any(item["artifact_id"] == "manifest" for item in manifest["artifact_refs"])
    assert any(item["path"] == "run_history.jsonl" for item in manifest["artifact_index"])
    validate_run_manifest(manifest, require_terminal_artifact=True)
    assert result.manifest["run_history_ref"] == "run_history.jsonl"


@pytest.mark.parametrize("run_id", ["../escape", "C:\\escape", "run:stream", "NUL"])
def test_workflow_rejects_unsafe_explicit_run_id_before_side_effect(
    tmp_path: Path,
    run_id: str,
) -> None:
    registry = StepRunnerRegistry()
    registry.register(StepType.FUNCTION, _Runner())
    workflow = WorkflowSpec(
        workflow_id="wf-manifest",
        name="Workflow",
        version="1.0",
        steps=[StepSpec(step_id="s1", write_keys=["ok"])],
        terminal_step_ids=["s1"],
    )

    with pytest.raises(ArtifactPathError):
        WorkflowExecutor(
            function_step_runner=None,
            artifact_manager=ArtifactManager(tmp_path),
            step_runner_registry=registry,
        ).execute(workflow, {}, profile="test", run_id=run_id)

    assert not tmp_path.exists() or not any(tmp_path.rglob("*"))
