from core.framework import WorkflowRunner
from core.framework.specs import StepSpec, WorkflowSpec, WorkflowStatus
from core.framework.workflow import FunctionStepRegistry


def test_workflow_runner_returns_stable_run_result(tmp_path) -> None:
    registry = FunctionStepRegistry()
    registry.register("sample.echo", lambda buffer: {"echo": buffer.read("request")})
    runner = WorkflowRunner(artifact_root=tmp_path, function_registry=registry)
    spec = WorkflowSpec(
        workflow_id="echo",
        name="Echo",
        version="1.0",
        start_step_id="echo",
        steps=[
            StepSpec(
                step_id="echo",
                implementation="sample.echo",
                read_keys=["request"],
                write_keys=["echo"],
                required_output_keys=["echo"],
            )
        ],
    )

    result = runner.run(spec, {"topic": "ai"}, profile="test", run_id="runner-success")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.run_id == "runner-success"
    assert result.workflow_id == "echo"
    assert result.workflow_version == "1.0"
    assert result.output["echo"] == {"topic": "ai"}
    assert result.artifact_dir is not None
    assert result.manifest_path is not None
    assert result.events_path is not None
    assert result.to_dict()["status"] == "succeeded"
