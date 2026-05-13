import json
import time
from hashlib import sha256

import pytest

from core.framework.artifacts import ArtifactManager
from core.framework.specs import (
    EdgeCondition,
    EdgeSpec,
    FailurePolicySpec,
    RetryPolicySpec,
    StepStatus,
    StepSpec,
    StepType,
    TimeoutPolicySpec,
    WorkflowSpec,
    WorkflowStatus,
)
from core.framework.workflow import (
    FunctionStepRegistry,
    FunctionStepRunner,
    HumanReviewStepRunner,
    StepExecutionError,
    StepOutcome,
    StepRunnerRegistry,
    WorkflowExecutor,
)
from storage.artifacts import ArtifactRef
from storage.checkpoint import LocalJsonCheckpointStore


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
        "edge_evaluated",
        "edge_traversed",
        "step_started",
        "step_succeeded",
        "workflow_succeeded",
    ]


def test_workflow_executor_writes_checkpoints_when_store_is_configured(tmp_path) -> None:
    registry = FunctionStepRegistry()
    registry.register("sample.plan", lambda buffer: {"plan": {"topic": buffer.read("request")["topic"]}})
    registry.register("sample.write", lambda buffer: {"report": f"Report: {buffer.read('plan')['topic']}"})
    checkpoint_store = LocalJsonCheckpointStore(tmp_path / "checkpoints")
    executor = WorkflowExecutor(
        function_step_runner=FunctionStepRunner(registry),
        artifact_manager=ArtifactManager(tmp_path / "runs"),
        checkpoint_store=checkpoint_store,
    )

    result = executor.execute(
        _sample_spec(),
        {"topic": "ai"},
        profile="test",
        run_id="run-checkpoints",
    )

    assert result.status == WorkflowStatus.SUCCEEDED
    checkpoints = checkpoint_store.list_checkpoints("run-checkpoints")
    assert len(checkpoints) == 2
    assert checkpoints[0].current_step_ids == ["write"]
    assert checkpoints[0].path == ["plan"]
    assert checkpoints[0].data_buffer_snapshot["plan"] == {"topic": "ai"}
    assert checkpoints[1].current_step_ids == []
    assert checkpoints[1].path == ["plan", "write"]
    assert checkpoints[1].data_buffer_snapshot["report"] == "Report: ai"
    assert set(checkpoints[1].step_results) == {"plan", "write"}

    manifest = json.loads((tmp_path / "runs" / "run-checkpoints" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["checkpoint_count"] == 2
    assert manifest["latest_checkpoint_id"] == checkpoints[1].checkpoint_id
    events = [
        json.loads(line)["event_type"]
        for line in (tmp_path / "runs" / "run-checkpoints" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert events == [
        "workflow_started",
        "step_started",
        "step_succeeded",
        "edge_evaluated",
        "edge_traversed",
        "checkpoint_created",
        "step_started",
        "step_succeeded",
        "checkpoint_created",
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


def test_workflow_executor_fails_step_on_timeout_without_retry(tmp_path) -> None:
    calls = {"count": 0}
    registry = FunctionStepRegistry()

    def slow(buffer):
        calls["count"] += 1
        time.sleep(0.05)
        raise RuntimeError("late failure")

    registry.register("sample.slow", slow)
    spec = WorkflowSpec(
        workflow_id="timeout",
        name="Timeout",
        version="1.0",
        start_step_id="slow",
        steps=[
            StepSpec(
                step_id="slow",
                implementation="sample.slow",
                retry_policy=RetryPolicySpec(max_retries=1, retry_delay_seconds=[0]),
                timeout_policy=TimeoutPolicySpec(timeout_seconds=0.01),
            )
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=FunctionStepRunner(registry),
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(spec, {"topic": "ai"}, profile="test", run_id="run-timeout")

    assert result.status == WorkflowStatus.FAILED
    assert result.step_results["slow"].status == StepStatus.TIMEOUT
    assert result.error is not None
    assert result.error.error_type == "WorkflowStepTimeoutError"
    assert result.error.details["timeout_seconds"] == 0.01
    assert calls["count"] == 1
    events = [
        json.loads(line)["event_type"]
        for line in (tmp_path / "run-timeout" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert "step_timeout" in events
    assert "step_retry_scheduled" not in events


def test_workflow_executor_retries_timeout_when_policy_allows(tmp_path) -> None:
    calls = {"count": 0}
    registry = FunctionStepRegistry()

    def slow_then_recover(buffer):
        calls["count"] += 1
        if calls["count"] == 1:
            time.sleep(0.05)
            raise RuntimeError("late failure")
        return {"report": "recovered after timeout"}

    registry.register("sample.slow_then_recover", slow_then_recover)
    spec = WorkflowSpec(
        workflow_id="timeout-retry",
        name="Timeout Retry",
        version="1.0",
        start_step_id="slow",
        steps=[
            StepSpec(
                step_id="slow",
                implementation="sample.slow_then_recover",
                write_keys=["report"],
                required_output_keys=["report"],
                retry_policy=RetryPolicySpec(
                    max_retries=1,
                    retry_delay_seconds=[0],
                    retry_on_error_types=["WorkflowStepTimeoutError"],
                ),
                timeout_policy=TimeoutPolicySpec(timeout_seconds=0.01, on_timeout="retry"),
            )
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=FunctionStepRunner(registry),
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(
        spec,
        {"topic": "ai"},
        profile="test",
        run_id="run-timeout-retry",
    )

    assert result.status == WorkflowStatus.SUCCEEDED
    assert calls["count"] == 2
    assert result.output["report"] == "recovered after timeout"
    events = [
        json.loads(line)["event_type"]
        for line in (tmp_path / "run-timeout-retry" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert events == [
        "workflow_started",
        "step_started",
        "step_timeout",
        "step_retry_scheduled",
        "step_started",
        "step_succeeded",
        "workflow_succeeded",
    ]
    workflow_spec = json.loads(
        (tmp_path / "run-timeout-retry" / "workflow_spec.json").read_text(encoding="utf-8")
    )
    assert workflow_spec["steps"][0]["timeout_policy"] == {
        "timeout_seconds": 0.01,
        "on_timeout": "retry",
    }


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


def test_workflow_executor_executes_fan_out_edges(tmp_path) -> None:
    registry = FunctionStepRegistry()
    registry.register("sample.start", lambda buffer: {"root": buffer.read("request")["topic"]})
    registry.register("sample.left", lambda buffer: {"left": f"left:{buffer.read('root')}"})
    registry.register("sample.right", lambda buffer: {"right": f"right:{buffer.read('root')}"})
    spec = WorkflowSpec(
        workflow_id="fan-out",
        name="Fan Out",
        version="1.0",
        start_step_id="start",
        steps=[
            StepSpec(
                step_id="start",
                implementation="sample.start",
                read_keys=["request"],
                write_keys=["root"],
                required_output_keys=["root"],
            ),
            StepSpec(
                step_id="left",
                implementation="sample.left",
                read_keys=["root"],
                write_keys=["left"],
                required_output_keys=["left"],
            ),
            StepSpec(
                step_id="right",
                implementation="sample.right",
                read_keys=["root"],
                write_keys=["right"],
                required_output_keys=["right"],
            ),
        ],
        edges=[
            EdgeSpec(
                "start-to-left",
                "start",
                "left",
                condition=EdgeCondition.ALWAYS,
                priority=0,
            ),
            EdgeSpec(
                "start-to-right",
                "start",
                "right",
                condition=EdgeCondition.ALWAYS,
                priority=1,
            ),
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=FunctionStepRunner(registry),
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(spec, {"topic": "ai"}, profile="test", run_id="run-fan-out")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.path == ["start", "left", "right"]
    assert result.output["left"] == "left:ai"
    assert result.output["right"] == "right:ai"
    events = [
        json.loads(line)["event_type"]
        for line in (tmp_path / "run-fan-out" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert events.count("edge_traversed") == 2


def test_workflow_executor_pauses_human_review_and_checkpoints(tmp_path) -> None:
    runner_registry = StepRunnerRegistry()
    runner_registry.register(StepType.HUMAN_REVIEW, _PausingHumanReviewRunner())
    checkpoint_store = LocalJsonCheckpointStore(tmp_path / "checkpoints")
    spec = WorkflowSpec(
        workflow_id="human-review",
        name="Human Review",
        version="1.0",
        start_step_id="review",
        steps=[
            StepSpec(
                step_id="review",
                implementation="human.review",
                step_type=StepType.HUMAN_REVIEW,
                read_keys=["request"],
                write_keys=["human_review_request"],
                required_output_keys=["human_review_request"],
            )
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=runner_registry,
        artifact_manager=ArtifactManager(tmp_path / "runs"),
        checkpoint_store=checkpoint_store,
    )

    result = executor.execute(spec, {"topic": "ai"}, profile="test", run_id="run-human-pause")

    assert result.status == WorkflowStatus.WAITING_FOR_HUMAN
    assert result.error is None
    assert result.output["human_review_request"]["topic"] == "ai"
    checkpoint = checkpoint_store.get_latest_checkpoint("run-human-pause")
    assert checkpoint is not None
    assert checkpoint.current_step_ids == ["review"]
    assert checkpoint.data_buffer_snapshot["human_review_request"]["topic"] == "ai"
    manifest = json.loads(
        (tmp_path / "runs" / "run-human-pause" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["status"] == "waiting_for_human"
    assert manifest["current_step_ids"] == ["review"]
    assert manifest["artifacts"]["pause"] == "pause.json"


def test_workflow_executor_resumes_from_human_review_checkpoint(tmp_path) -> None:
    function_registry = FunctionStepRegistry()
    function_registry.register(
        "sample.finalize",
        lambda buffer: {
            "report": (
                f"approved:{buffer.read('request')['topic']}:"
                f"{buffer.read('human_review_decision')['decision']}"
            )
        },
    )
    runner_registry = StepRunnerRegistry.with_function_runner(
        FunctionStepRunner(function_registry)
    )
    runner_registry.register(StepType.HUMAN_REVIEW, HumanReviewStepRunner())
    checkpoint_store = LocalJsonCheckpointStore(tmp_path / "checkpoints")
    spec = WorkflowSpec(
        workflow_id="human-resume",
        name="Human Resume",
        version="1.0",
        start_step_id="review",
        input_schema={"properties": {"human_review_decision": {"type": "object"}}},
        steps=[
            StepSpec(
                step_id="review",
                implementation="human.review",
                step_type=StepType.HUMAN_REVIEW,
                read_keys=["request", "human_review_decision"],
                write_keys=["human_review_request"],
            ),
            StepSpec(
                step_id="finalize",
                implementation="sample.finalize",
                read_keys=["request", "human_review_decision"],
                write_keys=["report"],
                required_output_keys=["report"],
            ),
        ],
        edges=[
            EdgeSpec(
                "review-approved",
                "review",
                "finalize",
                condition=EdgeCondition.HUMAN_APPROVED,
            )
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=runner_registry,
        artifact_manager=ArtifactManager(tmp_path / "runs"),
        checkpoint_store=checkpoint_store,
    )
    paused = executor.execute(spec, {"topic": "ai"}, profile="test", run_id="run-resume-source")
    checkpoint = checkpoint_store.get_latest_checkpoint("run-resume-source")

    assert paused.status == WorkflowStatus.WAITING_FOR_HUMAN
    assert checkpoint is not None

    resumed = executor.resume_from_checkpoint(
        spec,
        checkpoint,
        profile="test",
        run_id="run-resumed",
        buffer_updates={"human_review_decision": {"decision": "approved"}},
    )

    assert resumed.status == WorkflowStatus.SUCCEEDED
    assert resumed.path == ["review", "review", "finalize"]
    assert resumed.output["report"] == "approved:ai:approved"
    events = [
        json.loads(line)["event_type"]
        for line in (tmp_path / "runs" / "run-resumed" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert events[:2] == ["workflow_resumed", "checkpoint_restored"]


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


def test_workflow_executor_fails_when_step_visit_limit_is_exceeded(tmp_path) -> None:
    calls = {"count": 0}
    registry = FunctionStepRegistry()

    def loop(buffer):
        calls["count"] += 1
        return {"counter": calls["count"]}

    registry.register("sample.loop", loop)
    spec = WorkflowSpec(
        workflow_id="loop-limit",
        name="Loop Limit",
        version="1.0",
        start_step_id="loop",
        max_step_visits=2,
        steps=[
            StepSpec(
                step_id="loop",
                implementation="sample.loop",
                write_keys=["counter"],
                required_output_keys=["counter"],
            )
        ],
        edges=[EdgeSpec(edge_id="loop-self", source_step_id="loop", target_step_id="loop")],
    )
    executor = WorkflowExecutor(
        function_step_runner=FunctionStepRunner(registry),
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(spec, {"topic": "ai"}, profile="test", run_id="run-loop-limit")

    assert result.status == WorkflowStatus.FAILED
    assert calls["count"] == 2
    assert result.error is not None
    assert result.error.error_type == "WorkflowLoopLimitExceeded"
    assert result.error.details == {"max_step_visits": 2, "visit_count": 3}
    assert result.path == ["loop", "loop"]
    assert (tmp_path / "run-loop-limit" / "error.json").exists()
    events = [
        json.loads(line)["event_type"]
        for line in (tmp_path / "run-loop-limit" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert "workflow_loop_limit_exceeded" in events
    assert events[-1] == "workflow_failed"


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


def test_workflow_executor_records_step_artifact_refs(tmp_path) -> None:
    run_id = "run-step-artifact"
    runner_registry = StepRunnerRegistry()
    runner_registry.register(StepType.ARTIFACT, _StepArtifactRunner(tmp_path, run_id))
    spec = WorkflowSpec(
        workflow_id="step-artifact",
        name="Step Artifact",
        version="1.0",
        start_step_id="artifact",
        steps=[
            StepSpec(
                step_id="artifact",
                implementation="artifact.output",
                step_type=StepType.ARTIFACT,
                write_keys=["artifact_marker"],
                required_output_keys=["artifact_marker"],
            )
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=runner_registry,
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(spec, {"topic": "ai"}, profile="test", run_id=run_id)

    assert result.status == WorkflowStatus.SUCCEEDED
    manifest = json.loads((tmp_path / run_id / "manifest.json").read_text(encoding="utf-8"))
    artifact_key = "step.artifact.step_output.artifact-output"
    assert manifest["artifacts"][artifact_key] == "steps/artifact/output.json"
    assert manifest["step_artifacts"][0]["artifact_id"] == "artifact-output"
    assert manifest["steps"]["artifact"]["artifacts"][0]["path"] == "steps/artifact/output.json"
    assert (tmp_path / run_id / "steps" / "artifact" / "output.json").exists()


def test_workflow_executor_rejects_missing_runner_before_run_creation(tmp_path) -> None:
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

    with pytest.raises(StepExecutionError, match="not registered: artifact"):
        executor.execute(spec, {"topic": "ai"}, profile="test", run_id="run-missing-runner")

    assert not (tmp_path / "run-missing-runner").exists()


class _ArtifactMarkerRunner:
    def run(self, step: StepSpec, buffer) -> StepOutcome:
        output = {
            "artifact_id": step.metadata["artifact_id"],
            "implementation": step.implementation,
        }
        buffer.write("artifact_marker", output)
        return StepOutcome(status=StepStatus.SUCCEEDED, outputs={"artifact_marker": output})


class _StepArtifactRunner:
    def __init__(self, artifact_root, run_id: str) -> None:
        self._run_dir = artifact_root / run_id
        self._run_id = run_id

    def run(self, step: StepSpec, buffer) -> StepOutcome:
        output = {"artifact": "real", "implementation": step.implementation}
        relative_path = "steps/artifact/output.json"
        target = self._run_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(output, sort_keys=True).encode("utf-8")
        target.write_bytes(content)
        buffer.write("artifact_marker", "written")
        return StepOutcome(
            status=StepStatus.SUCCEEDED,
            outputs={"artifact_marker": "written"},
            artifacts=[
                ArtifactRef(
                    artifact_id="artifact-output",
                    run_id=self._run_id,
                    step_id=step.step_id,
                    artifact_type="step_output",
                    path=relative_path,
                    content_type="application/json",
                    size_bytes=len(content),
                    checksum=sha256(content).hexdigest(),
                    redacted=True,
                    metadata={"source": "custom_runner"},
                )
            ],
        )


class _PausingHumanReviewRunner:
    def run(self, step: StepSpec, buffer) -> StepOutcome:
        request = {"topic": buffer.read("request")["topic"], "step_id": step.step_id}
        buffer.write("human_review_request", request)
        return StepOutcome(
            status=StepStatus.PAUSED,
            outputs={"human_review_request": request},
            next_hint="human_review",
        )
