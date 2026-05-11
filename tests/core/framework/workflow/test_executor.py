import json

from core.framework.artifacts import ArtifactManager
from core.framework.specs import (
    EdgeCondition,
    EdgeSpec,
    FailurePolicySpec,
    RetryPolicySpec,
    StepStatus,
    StepSpec,
    StepType,
    WorkflowSpec,
    WorkflowStatus,
)
from core.framework.workflow import (
    FunctionStepRegistry,
    FunctionStepRunner,
    StepOutcome,
    StepRunnerRegistry,
    WorkflowExecutor,
)


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
    assert (run_dir / "data_buffer.initial.json").exists()
    assert (run_dir / "data_buffer.final.json").exists()
    assert (run_dir / "data_buffer.diff.json").exists()
    assert (run_dir / "output.json").exists()

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "succeeded"
    assert manifest["profile"] == "test"
    assert manifest["path"] == ["plan", "write"]
    assert manifest["artifacts"]["events"] == "events.jsonl"
    assert manifest["artifacts"]["data_buffer_snapshot"] == "data_buffer_snapshot.json"
    assert manifest["artifacts"]["data_buffer_initial"] == "data_buffer.initial.json"
    assert manifest["artifacts"]["data_buffer_final"] == "data_buffer.final.json"
    assert manifest["artifacts"]["data_buffer_diff"] == "data_buffer.diff.json"

    initial_buffer = json.loads((run_dir / "data_buffer.initial.json").read_text(encoding="utf-8"))
    final_buffer = json.loads((run_dir / "data_buffer.final.json").read_text(encoding="utf-8"))
    buffer_diff = json.loads((run_dir / "data_buffer.diff.json").read_text(encoding="utf-8"))
    assert initial_buffer == {"request": {"topic": "ai"}}
    assert final_buffer["report"] == "Report: ai"
    assert buffer_diff == {
        "added": {
            "plan": {"topic": "ai"},
            "report": "Report: ai",
        },
        "changed": {},
        "removed": {},
    }

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


def test_workflow_executor_retries_step_and_succeeds(tmp_path) -> None:
    calls = {"count": 0}
    registry = FunctionStepRegistry()

    def flaky(buffer):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary failure")
        return {"report": "recovered"}

    registry.register("sample.flaky", flaky)
    spec = WorkflowSpec(
        workflow_id="retry",
        name="Retry",
        version="1.0",
        start_step_id="flaky",
        steps=[
            StepSpec(
                step_id="flaky",
                implementation="sample.flaky",
                write_keys=["report"],
                required_output_keys=["report"],
                retry_policy=RetryPolicySpec(
                    max_retries=1,
                    retry_delay_seconds=[0],
                    retry_on_error_types=["RuntimeError"],
                ),
            )
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=FunctionStepRunner(registry),
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(spec, {"topic": "ai"}, profile="test", run_id="run-retry")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert calls["count"] == 2
    assert result.output["report"] == "recovered"
    events = [
        json.loads(line)["event_type"]
        for line in (tmp_path / "run-retry" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert events == [
        "workflow_started",
        "step_started",
        "step_retry_scheduled",
        "step_started",
        "step_succeeded",
        "workflow_succeeded",
    ]
    workflow_spec = json.loads((tmp_path / "run-retry" / "workflow_spec.json").read_text(encoding="utf-8"))
    assert workflow_spec["steps"][0]["retry_policy"]["max_retries"] == 1


def test_workflow_executor_does_not_retry_no_retry_error_type(tmp_path) -> None:
    calls = {"count": 0}
    registry = FunctionStepRegistry()

    def bad_request(buffer):
        calls["count"] += 1
        raise ValueError("invalid input")

    registry.register("sample.bad_request", bad_request)
    spec = WorkflowSpec(
        workflow_id="no-retry",
        name="No Retry",
        version="1.0",
        start_step_id="bad",
        steps=[
            StepSpec(
                step_id="bad",
                implementation="sample.bad_request",
                retry_policy=RetryPolicySpec(
                    max_retries=2,
                    no_retry_on_error_types=["ValueError"],
                ),
            )
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=FunctionStepRunner(registry),
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(spec, {"topic": "ai"}, profile="test", run_id="run-no-retry")

    assert result.status == WorkflowStatus.FAILED
    assert calls["count"] == 1
    assert result.error is not None
    assert result.error.message == "invalid input"
    events = (tmp_path / "run-no-retry" / "events.jsonl").read_text(encoding="utf-8")
    assert "step_retry_scheduled" not in events


def test_workflow_executor_fails_after_retry_exhaustion(tmp_path) -> None:
    calls = {"count": 0}
    registry = FunctionStepRegistry()

    def always_bad(buffer):
        calls["count"] += 1
        raise RuntimeError(f"still failing {calls['count']}")

    registry.register("sample.always_bad", always_bad)
    spec = WorkflowSpec(
        workflow_id="retry-exhausted",
        name="Retry Exhausted",
        version="1.0",
        start_step_id="bad",
        steps=[
            StepSpec(
                step_id="bad",
                implementation="sample.always_bad",
                retry_policy=RetryPolicySpec(max_retries=2, retry_delay_seconds=[0, 0]),
            )
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=FunctionStepRunner(registry),
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(spec, {"topic": "ai"}, profile="test", run_id="run-exhausted")

    assert result.status == WorkflowStatus.FAILED
    assert calls["count"] == 3
    assert result.error is not None
    assert result.error.message == "still failing 3"
    events = [
        json.loads(line)["event_type"]
        for line in (tmp_path / "run-exhausted" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert events.count("step_retry_scheduled") == 2


def test_workflow_executor_routes_failed_step_to_policy_fallback(tmp_path) -> None:
    registry = FunctionStepRegistry()
    registry.register("sample.bad", lambda buffer: (_ for _ in ()).throw(RuntimeError("primary failed")))
    registry.register("sample.recover", lambda buffer: {"report": "recovered"})
    spec = WorkflowSpec(
        workflow_id="fallback-policy",
        name="Fallback Policy",
        version="1.0",
        start_step_id="bad",
        steps=[
            StepSpec(
                step_id="bad",
                implementation="sample.bad",
                failure_policy=FailurePolicySpec(fallback_step_id="recover"),
            ),
            StepSpec(
                step_id="recover",
                implementation="sample.recover",
                write_keys=["report"],
                required_output_keys=["report"],
            ),
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=FunctionStepRunner(registry),
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(spec, {"topic": "ai"}, profile="test", run_id="run-policy-fallback")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.error is None
    assert result.path == ["bad", "recover"]
    assert result.output["report"] == "recovered"
    assert result.step_results["bad"].status == StepStatus.FAILED
    events = [
        json.loads(line)["event_type"]
        for line in (tmp_path / "run-policy-fallback" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert events == [
        "workflow_started",
        "step_started",
        "step_failed",
        "step_started",
        "step_succeeded",
        "workflow_succeeded",
    ]


def test_workflow_executor_routes_failed_step_to_on_failure_edge(tmp_path) -> None:
    registry = FunctionStepRegistry()
    registry.register("sample.bad", lambda buffer: (_ for _ in ()).throw(RuntimeError("primary failed")))
    registry.register("sample.recover", lambda buffer: {"report": "edge recovered"})
    spec = WorkflowSpec(
        workflow_id="fallback-edge",
        name="Fallback Edge",
        version="1.0",
        start_step_id="bad",
        steps=[
            StepSpec(step_id="bad", implementation="sample.bad"),
            StepSpec(
                step_id="recover",
                implementation="sample.recover",
                write_keys=["report"],
                required_output_keys=["report"],
            ),
        ],
        edges=[
            EdgeSpec(
                edge_id="bad-to-recover",
                source_step_id="bad",
                target_step_id="recover",
                condition=EdgeCondition.ON_FAILURE,
            )
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=FunctionStepRunner(registry),
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(spec, {"topic": "ai"}, profile="test", run_id="run-edge-fallback")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.path == ["bad", "recover"]
    assert result.output["report"] == "edge recovered"


def test_workflow_executor_marks_failed_step_as_blocked(tmp_path) -> None:
    registry = FunctionStepRegistry()
    registry.register("sample.bad", lambda buffer: (_ for _ in ()).throw(RuntimeError("needs review")))
    spec = WorkflowSpec(
        workflow_id="blocked-policy",
        name="Blocked Policy",
        version="1.0",
        start_step_id="bad",
        steps=[
            StepSpec(
                step_id="bad",
                implementation="sample.bad",
                failure_policy=FailurePolicySpec(mark_as_blocked=True),
            )
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=FunctionStepRunner(registry),
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(spec, {"topic": "ai"}, profile="test", run_id="run-blocked-policy")

    assert result.status == WorkflowStatus.BLOCKED
    assert result.error is not None
    assert result.error.message == "needs review"
    assert (tmp_path / "run-blocked-policy" / "error.json").exists()
    manifest = json.loads((tmp_path / "run-blocked-policy" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "blocked"
    events = [
        json.loads(line)["event_type"]
        for line in (tmp_path / "run-blocked-policy" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert events == [
        "workflow_started",
        "step_started",
        "step_failed",
        "step_blocked",
        "workflow_blocked",
    ]


def test_workflow_executor_records_routing_failure_artifacts(tmp_path) -> None:
    registry = FunctionStepRegistry()
    registry.register("sample.decide", lambda buffer: {"decision": "publish"})
    registry.register("sample.publish", lambda buffer: {"report": "published"})
    spec = WorkflowSpec(
        workflow_id="routing-failure",
        name="Routing Failure",
        version="1.0",
        start_step_id="decide",
        steps=[
            StepSpec(
                step_id="decide",
                implementation="sample.decide",
                write_keys=["decision"],
                required_output_keys=["decision"],
            ),
            StepSpec(
                step_id="publish",
                implementation="sample.publish",
                write_keys=["report"],
                required_output_keys=["report"],
            ),
        ],
        edges=[
            EdgeSpec(
                edge_id="unsafe-route",
                source_step_id="decide",
                target_step_id="publish",
                condition=EdgeCondition.CONDITIONAL,
                condition_expr='__import__("os").system("echo unsafe")',
            )
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=FunctionStepRunner(registry),
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(spec, {"topic": "ai"}, profile="test", run_id="run-routing-failed")

    assert result.status == WorkflowStatus.FAILED
    assert result.error is not None
    assert result.error.step_id == "decide"
    assert result.error.details == {"phase": "routing"}
    assert result.error.error_type == "ConditionalExpressionError"
    assert (tmp_path / "run-routing-failed" / "error.json").exists()
    events = (tmp_path / "run-routing-failed" / "events.jsonl").read_text(encoding="utf-8")
    assert "step_succeeded" in events
    assert "workflow_failed" in events


def test_workflow_executor_dispatches_custom_step_runner(tmp_path) -> None:
    runner_registry = StepRunnerRegistry()
    runner_registry.register(StepType.ARTIFACT, _ArtifactMarkerRunner())
    spec = WorkflowSpec(
        workflow_id="custom-runner",
        name="Custom Runner",
        version="1.0",
        start_step_id="artifact",
        steps=[
            StepSpec(
                step_id="artifact",
                implementation="artifact.marker",
                step_type=StepType.ARTIFACT,
                write_keys=["artifact_marker"],
                required_output_keys=["artifact_marker"],
                metadata={"artifact_id": "artifact-1"},
            )
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=runner_registry,
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(spec, {"topic": "ai"}, profile="test", run_id="run-custom-runner")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["artifact_marker"] == {
        "artifact_id": "artifact-1",
        "implementation": "artifact.marker",
    }
    assert (tmp_path / "run-custom-runner" / "manifest.json").exists()
    events = [
        json.loads(line)["event_type"]
        for line in (tmp_path / "run-custom-runner" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert events == [
        "workflow_started",
        "step_started",
        "step_succeeded",
        "workflow_succeeded",
    ]


def test_workflow_executor_fails_step_when_runner_is_missing(tmp_path) -> None:
    spec = WorkflowSpec(
        workflow_id="missing-runner",
        name="Missing Runner",
        version="1.0",
        start_step_id="artifact",
        steps=[
            StepSpec(
                step_id="artifact",
                implementation="artifact.marker",
                step_type=StepType.ARTIFACT,
                write_keys=["artifact_marker"],
                required_output_keys=["artifact_marker"],
            )
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=FunctionStepRunner(FunctionStepRegistry()),
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(spec, {"topic": "ai"}, profile="test", run_id="run-missing-runner")

    assert result.status == WorkflowStatus.FAILED
    assert result.error is not None
    assert result.error.error_type == "StepExecutionError"
    assert result.error.message == "step runner is not registered: artifact"
    assert (tmp_path / "run-missing-runner" / "error.json").exists()
    events = (tmp_path / "run-missing-runner" / "events.jsonl").read_text(encoding="utf-8")
    assert "step_failed" in events


class _ArtifactMarkerRunner:
    def run(self, step: StepSpec, buffer) -> StepOutcome:
        output = {
            "artifact_id": step.metadata["artifact_id"],
            "implementation": step.implementation,
        }
        buffer.write("artifact_marker", output)
        return StepOutcome(status=StepStatus.SUCCEEDED, outputs={"artifact_marker": output})
