from core.framework.artifacts import ArtifactManager
from core.framework.specs import StepSpec, StepType, WorkflowSpec, WorkflowStatus
from core.framework.workflow import (
    FunctionStepRegistry,
    FunctionStepRunner,
    StepRunnerRegistry,
    SubworkflowStepRunner,
    WorkflowExecutor,
)


def test_subworkflow_runner_maps_outputs_and_records_lineage(tmp_path) -> None:
    functions = FunctionStepRegistry()
    functions.register("child.echo", lambda buffer: {"echo": buffer.read("request")["topic"]})
    registry = StepRunnerRegistry.with_function_runner(FunctionStepRunner(functions))
    child = WorkflowSpec(
        workflow_id="child",
        name="Child",
        version="1.0",
        start_step_id="echo",
        steps=[StepSpec("echo", "child.echo", read_keys=["request"], write_keys=["echo"])],
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
                read_keys=["request"],
                write_keys=["subworkflow_result", "child_echo"],
                required_output_keys=["subworkflow_result", "child_echo"],
                metadata={
                    "workflow_id": "child",
                    "request_key": "request",
                    "output_map": {"child_echo": "echo"},
                },
            )
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(parent, {"topic": "ai"}, profile="test", run_id="run-parent")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["child_echo"] == "ai"
    assert result.step_results["child"].lineage[0]["child_run_id"] == "run-parent.child.child"
    assert (tmp_path / "run-parent.child.child" / "manifest.json").exists()


def test_subworkflow_runner_failed_child_maps_to_failed_parent_outcome(tmp_path) -> None:
    functions = FunctionStepRegistry()
    functions.register("child.fail", lambda buffer: (_ for _ in ()).throw(RuntimeError("boom")))
    registry = StepRunnerRegistry.with_function_runner(FunctionStepRunner(functions))
    child = WorkflowSpec(
        workflow_id="child",
        name="Child",
        version="1.0",
        start_step_id="fail",
        steps=[StepSpec("fail", "child.fail")],
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
                write_keys=["subworkflow_result"],
                metadata={"workflow_id": "child"},
            )
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(parent, {}, profile="test", run_id="run-parent-failed")

    assert result.status == WorkflowStatus.FAILED
    assert result.step_results["child"].error_type == "RuntimeError"
    assert result.output["subworkflow_result"]["status"] == "failed"
    assert result.step_results["child"].metrics["child_status"] == "failed"
