from __future__ import annotations

from typing import Any

from framework import WorkflowRunner
from framework.specs import EdgeSpec, StepSpec, WorkflowSpec, WorkflowStatus
from framework.workflow import FunctionStepRegistry
from framework.workflow.buffer.data_buffer import StepScopedDataBufferView
from framework.workflow.checkpoint.store import LocalJsonCheckpointStore


def test_approval_resume_context_can_resume_from_metadata_target_step(tmp_path) -> None:
    checkpoint_store = LocalJsonCheckpointStore(tmp_path / "checkpoints")
    runner = WorkflowRunner(
        artifact_root=tmp_path / "runs",
        function_registry=_registry(),
        checkpoint_store=checkpoint_store,
    )
    workflow = _workflow()
    source = runner.run(
        workflow,
        {},
        profile="test",
        run_id="source-run",
    )

    resumed = runner.resume_from_approval_context(
        workflow,
        {
            "buffer_updates": {"patch_marker": "patched"},
            "resume_metadata": {
                "approval_run_id": "source-run",
                "resume_next_step_id": "s2",
                "allowed_patch_keys": ["patch_marker"],
            },
        },
        profile="test",
        run_id="resumed-run",
    )

    assert source.status == WorkflowStatus.SUCCEEDED
    assert source.output["c"] == "a:initial"
    assert resumed.status == WorkflowStatus.SUCCEEDED
    assert resumed.output["c"] == "a:patched"
    assert resumed.manifest["resumed_from_checkpoint_id"]
    assert resumed.manifest["resume_mode"] == "resume_from_step"
    assert resumed.manifest["resume_target_step_id"] == "s2"
    assert resumed.manifest["resume_patch_keys"] == ["patch_marker"]


def _workflow() -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="wf-approval-resume-target",
        name="Approval Resume Target",
        version="1",
        steps=[
            StepSpec("s1", implementation="test.s1", write_keys=["a", "patch_marker"]),
            StepSpec(
                "s2",
                implementation="test.s2",
                read_keys=["a", "patch_marker"],
                write_keys=["b"],
            ),
            StepSpec("s3", implementation="test.s3", read_keys=["b"], write_keys=["c"]),
        ],
        edges=[
            EdgeSpec("s1-to-s2", "s1", "s2"),
            EdgeSpec("s2-to-s3", "s2", "s3"),
        ],
        terminal_step_ids=["s3"],
    )


def _registry() -> FunctionStepRegistry:
    registry = FunctionStepRegistry()
    registry.register("test.s1", _s1)
    registry.register("test.s2", _s2)
    registry.register("test.s3", _s3)
    return registry


def _s1(buffer: StepScopedDataBufferView) -> dict[str, Any]:
    return {"a": "a", "patch_marker": "initial"}


def _s2(buffer: StepScopedDataBufferView) -> dict[str, Any]:
    return {"b": f"{buffer.read('a')}:{buffer.read('patch_marker')}"}


def _s3(buffer: StepScopedDataBufferView) -> dict[str, Any]:
    return {"c": buffer.read("b")}
