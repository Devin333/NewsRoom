import json

from core.framework.artifacts import ArtifactManager
from core.framework.specs import EdgeSpec, StepSpec, WorkflowSpec, WorkflowStatus
from core.framework.workflow import FunctionStepRegistry, FunctionStepRunner, WorkflowExecutor


def _sample_spec() -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="sample",
        name="Sample",
        version="1.0",
        start_step_id="plan",
        steps=[
            StepSpec(
                step_id="plan",
                implementation="sample.plan",
                read_keys=["request"],
                write_keys=["plan"],
                required_output_keys=["plan"],
            ),
            StepSpec(
                step_id="write",
                implementation="sample.write",
                read_keys=["plan"],
                write_keys=["report"],
                required_output_keys=["report"],
            ),
        ],
        edges=[EdgeSpec(edge_id="plan-to-write", source_step_id="plan", target_step_id="write")],
    )


def test_workflow_executor_runs_function_steps_and_writes_artifacts(tmp_path) -> None:
    registry = FunctionStepRegistry()
    registry.register("sample.plan", lambda buffer: {"plan": {"topic": buffer.read("request")["topic"]}})
    registry.register("sample.write", lambda buffer: {"report": f"Report: {buffer.read('plan')['topic']}"})
    executor = WorkflowExecutor(
        function_step_runner=FunctionStepRunner(registry),
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(
        _sample_spec(),
        {"topic": "ai"},
        profile="test",
        run_id="run-success",
    )

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.path == ["plan", "write"]
    assert result.output["report"] == "Report: ai"

    run_dir = tmp_path / "run-success"
    assert (run_dir / "request.json").exists()
    assert (run_dir / "workflow_spec.json").exists()
    assert (run_dir / "events.jsonl").exists()
    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "data_buffer_snapshot.json").exists()
    assert (run_dir / "output.json").exists()

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "succeeded"
    assert manifest["profile"] == "test"
    assert manifest["path"] == ["plan", "write"]
    assert manifest["artifacts"]["events"] == "events.jsonl"

    events = [
        json.loads(line)
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [event["event_type"] for event in events] == [
        "workflow_started",
        "step_started",
        "step_succeeded",
        "step_started",
        "step_succeeded",
        "workflow_succeeded",
    ]


def test_workflow_executor_records_step_failure_artifacts(tmp_path) -> None:
    registry = FunctionStepRegistry()
    registry.register("sample.bad", lambda buffer: {"plan": buffer.read("request")})
    spec = WorkflowSpec(
        workflow_id="sample",
        name="Sample",
        version="1.0",
        start_step_id="bad",
        steps=[
            StepSpec(
                step_id="bad",
                implementation="sample.bad",
                read_keys=[],
                write_keys=["plan"],
                required_output_keys=["plan"],
            )
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=FunctionStepRunner(registry),
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(spec, {"topic": "ai"}, profile="test", run_id="run-failed")

    assert result.status == WorkflowStatus.FAILED
    assert result.error is not None
    assert result.error.step_id == "bad"
    assert result.output == {"request": {"topic": "ai"}}
    assert (tmp_path / "run-failed" / "error.json").exists()

    events = (tmp_path / "run-failed" / "events.jsonl").read_text(encoding="utf-8")
    assert "step_failed" in events
    assert "workflow_failed" in events
