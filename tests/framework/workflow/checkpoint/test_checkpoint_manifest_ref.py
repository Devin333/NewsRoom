from __future__ import annotations

from framework.specs import StepSpec
from framework.workflow.checkpoint.model import WorkflowCheckpoint
from framework.workflow.runtime.artifacts import ArtifactManager
from framework.workflow.runtime.checkpoint_coordinator import CheckpointCoordinator
from framework.workflow.runtime.execution_context import build_execution_context
from framework.workflow.runtime.result import StepOutcome


class _CheckpointStore:
    def __init__(self) -> None:
        self.saved: list[WorkflowCheckpoint] = []

    def save_checkpoint(self, checkpoint: WorkflowCheckpoint) -> None:
        self.saved.append(checkpoint)


def test_checkpoint_coordinator_records_checkpoint_reference(tmp_path) -> None:
    from framework.specs import WorkflowSpec
    from framework.workflow.runners.registry import StepRunnerRegistry

    step = StepSpec(step_id="s1", write_keys=["ok"])
    workflow = WorkflowSpec(
        workflow_id="wf-checkpoint",
        name="Workflow",
        version="1.0",
        steps=[step],
        terminal_step_ids=["s1"],
    )
    context = build_execution_context(
        workflow=workflow,
        request={},
        profile="test",
        artifact_manager=ArtifactManager(tmp_path),
        step_runner_registry=StepRunnerRegistry(),
        event_bus=None,
        started_monotonic=0.0,
        run_id="run-checkpoint-ref",
    )
    context.path.append("s1")
    context.step_results["s1"] = StepOutcome.success("s1", {"ok": True})

    checkpoint_id = CheckpointCoordinator(checkpoint_store=_CheckpointStore()).write_checkpoint(
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

    assert checkpoint_id is not None
    assert context.manifest["checkpoint_ref"] == checkpoint_id
    assert context.manifest["latest_checkpoint_id"] == checkpoint_id
    assert context.manifest["checkpoint_refs"][0]["checkpoint_id"] == checkpoint_id
    assert context.step_results["s1"].checkpoint_ref == checkpoint_id
