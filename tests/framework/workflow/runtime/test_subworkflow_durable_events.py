from __future__ import annotations

from framework import WorkflowRunner
from framework.specs import StepSpec, StepType, WorkflowSpec, WorkflowStatus
from framework.workflow import FunctionStepRegistry
from framework.workflow.buffer import StepScopedDataBufferView
from infrastructure.storage.events.factory import durable_event_storage_from_env


def test_subworkflow_inherits_canonical_event_runtime_and_reader(tmp_path) -> None:
    child = WorkflowSpec(
        workflow_id="child-workflow",
        name="Child workflow",
        version="1",
        steps=[
            StepSpec(
                "child-step",
                implementation="test.child",
                write_keys=["child_value"],
            )
        ],
        terminal_step_ids=["child-step"],
    )
    parent = WorkflowSpec(
        workflow_id="parent-workflow",
        name="Parent workflow",
        version="1",
        steps=[
            StepSpec(
                "run-child",
                step_type=StepType.SUBWORKFLOW,
                implementation=child.workflow_id,
                write_keys=["subworkflow_result", "parent_value"],
                metadata={
                    "workflow_id": child.workflow_id,
                    "output_map": {"parent_value": "child_value"},
                },
            )
        ],
        terminal_step_ids=["run-child"],
    )
    registry = FunctionStepRegistry()
    registry.register("test.child", _child_step)
    storage = durable_event_storage_from_env(
        artifact_root=tmp_path / "runs",
        env={},
    )
    runner = WorkflowRunner(
        artifact_root=tmp_path / "runs",
        function_registry=registry,
        workflow_registry={child.workflow_id: child},
        event_runtime=storage.event_runtime,
        event_reader=storage.event_store,
        event_schema_catalog=storage.schema_catalog,
    )

    result = runner.run(parent, {}, profile="test", run_id="parent-run")

    child_run_id = "parent-run.run-child.child-workflow"
    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["parent_value"] == "durable-child"
    assert storage.event_store.get_stream_high_watermark("run:parent-run") is not None
    assert storage.event_store.get_stream_high_watermark(f"run:{child_run_id}") is not None


def _child_step(_buffer: StepScopedDataBufferView) -> dict[str, str]:
    return {"child_value": "durable-child"}
