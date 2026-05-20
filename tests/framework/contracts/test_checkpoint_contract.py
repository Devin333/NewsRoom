from __future__ import annotations

from framework.specs import StepSpec, WorkflowSpec
from framework.workflow.checkpoint.envelope import envelope_from_checkpoint, envelope_to_checkpoint
from framework.workflow.checkpoint.model import WorkflowCheckpoint
from framework.workflow.runtime.artifacts import ArtifactManager
from framework.workflow.runtime.checkpoint_coordinator import CheckpointCoordinator
from framework.workflow.runtime.execution_context import build_execution_context
from framework.workflow.runtime.result import StepOutcome
from framework.workflow.runners.registry import StepRunnerRegistry


class _CheckpointStore:
    def __init__(self) -> None:
        self.saved: list[WorkflowCheckpoint] = []

    def save_checkpoint(self, checkpoint: WorkflowCheckpoint) -> None:
        self.saved.append(checkpoint)


def test_checkpoint_contract_manifest_refs_and_round_trip(tmp_path) -> None:
    workflow = WorkflowSpec(
        workflow_id="wf-checkpoint-contract",
        name="Workflow",
        version="1.0",
        steps=[StepSpec(step_id="s1", write_keys=["ok"])],
        terminal_step_ids=["s1"],
    )
    context = build_execution_context(
        workflow=workflow,
        request={},
        profile="contract",
        artifact_manager=ArtifactManager(tmp_path),
        step_runner_registry=StepRunnerRegistry(),
        event_bus=None,
        started_monotonic=0.0,
        run_id="run-checkpoint-contract",
    )
    context.path.append("s1")
    context.step_results["s1"] = StepOutcome.success("s1", {"ok": True})
    store = _CheckpointStore()

    checkpoint_id = CheckpointCoordinator(checkpoint_store=store).write_checkpoint(
        run_id=context.run_id,
        workflow=context.workflow,
        profile=context.profile,
        current_step_ids=[],
        buffer=context.buffer,
        step_results=context.step_results,
        path=context.path,
        recorder=context.recorder,
        manifest=context.manifest,
        checkpoint_ids=context.checkpoint_ids,
    )
    envelope = envelope_from_checkpoint(store.saved[0])
    restored = envelope_to_checkpoint(envelope)

    assert checkpoint_id is not None
    assert context.manifest["checkpoint_ref"] == checkpoint_id
    assert context.manifest["latest_checkpoint_id"] == checkpoint_id
    assert context.manifest["checkpoint_refs"][0]["checkpoint_id"] == checkpoint_id
    assert context.step_results["s1"].checkpoint_ref == checkpoint_id
    assert restored.checkpoint_id == checkpoint_id
