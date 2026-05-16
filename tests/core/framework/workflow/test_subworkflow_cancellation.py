from __future__ import annotations

from core.framework.artifacts import ArtifactManager
from core.framework.specs import StepSpec, StepType, WorkflowSpec
from core.framework.workflow import (
    FunctionStepRegistry,
    FunctionStepRunner,
    StepRunnerRegistry,
    SubworkflowStepRunner,
    WorkflowExecutor,
)


def test_subworkflow_cancellation_policy_default_cascades(tmp_path) -> None:
    result = _run_parent_with_child(
        tmp_path,
        child_function=lambda buffer: {"echo": "ok"},
        parent_write_keys=["subworkflow_result", "subworkflow_cancellation_policy"],
    )

    assert result.output["subworkflow_cancellation_policy"] == {"cascade": True}
    assert result.step_results["child"].lineage[0]["cancellation_policy"] == {"cascade": True}


def test_subworkflow_cancellation_policy_can_disable_cascade(tmp_path) -> None:
    result = _run_parent_with_child(
        tmp_path,
        child_function=lambda buffer: {"echo": "ok"},
        parent_write_keys=["subworkflow_result", "subworkflow_cancellation_policy"],
        step_metadata={"cancellation_policy": {"cascade": False}},
    )

    assert result.output["subworkflow_cancellation_policy"] == {"cascade": False}
    assert result.step_results["child"].metrics["cancellation_policy"] == {"cascade": False}


def _run_parent_with_child(
    tmp_path,
    *,
    child_function,
    parent_write_keys: list[str],
    step_metadata: dict | None = None,
):
    functions = FunctionStepRegistry()
    functions.register("child.fn", child_function)
    registry = StepRunnerRegistry.with_function_runner(FunctionStepRunner(functions))
    child = WorkflowSpec(
        workflow_id="child",
        name="Child",
        version="1.0",
        start_step_id="echo",
        steps=[StepSpec("echo", "child.fn", write_keys=["echo"])],
    )
    registry.register(StepType.SUBWORKFLOW, SubworkflowStepRunner({"child": child}, registry))
    parent = WorkflowSpec(
        workflow_id="parent",
        name="Parent",
        version="1.0",
        start_step_id="child",
        steps=[
            StepSpec(
                "child",
                "child",
                step_type=StepType.SUBWORKFLOW,
                write_keys=parent_write_keys,
                metadata={"workflow_id": "child", **dict(step_metadata or {})},
            )
        ],
    )
    return WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path),
    ).execute(parent, {}, profile="test", run_id="run-parent")
