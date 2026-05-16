from __future__ import annotations

from datetime import UTC, datetime, timedelta

from core.framework.artifacts import ArtifactManager
from core.framework.specs import EdgeSpec, StepSpec, StepStatus, StepType, WorkflowSpec, WorkflowStatus
from core.framework.workflow import (
    DataBuffer,
    FunctionStepRegistry,
    FunctionStepRunner,
    JoinStepRunner,
    StepRunnerRegistry,
    WorkflowExecutor,
)


def _join_outcome(
    *,
    metadata: dict,
    inputs: dict,
    read_keys: list[str] | None = None,
):
    buffer = DataBuffer(inputs)
    step = StepSpec(
        "join",
        "join.inputs",
        step_type=StepType.JOIN,
        read_keys=read_keys or list(inputs),
        write_keys=["join_result"],
        required_output_keys=["join_result"],
        metadata=metadata,
    )
    return JoinStepRunner().run(
        step,
        buffer.scope(read_keys=step.read_keys, write_keys=["join_result"]),
    )


def test_join_all_success_passes_when_all_required_succeeded() -> None:
    outcome = _join_outcome(
        metadata={
            "join_policy": "all_success",
            "required_upstream_step_ids": ["fetch_github", "fetch_arxiv"],
        },
        inputs={
            "upstream_statuses": {
                "fetch_github": "succeeded",
                "fetch_arxiv": "succeeded",
            }
        },
    )

    result = outcome.outputs["join_result"]
    assert outcome.status == StepStatus.SUCCEEDED
    assert result["ready"] is True
    assert result["decision"] == "joined"
    assert result["succeeded_upstreams"] == ["fetch_arxiv", "fetch_github"]


def test_join_all_success_fails_when_required_failed() -> None:
    outcome = _join_outcome(
        metadata={
            "join_policy": "all_success",
            "required_upstream_step_ids": ["fetch_github", "fetch_arxiv"],
        },
        inputs={
            "upstream_statuses": {
                "fetch_github": "succeeded",
                "fetch_arxiv": "failed",
            }
        },
    )

    result = outcome.outputs["join_result"]
    assert result["ready"] is False
    assert result["decision"] == "failed_upstream"
    assert result["failed_upstreams"] == ["fetch_arxiv"]


def test_join_any_success_passes_with_one_success() -> None:
    outcome = _join_outcome(
        metadata={
            "join_policy": "any_success",
            "required_upstream_step_ids": ["fetch_github", "fetch_arxiv"],
        },
        inputs={
            "upstream_statuses": {
                "fetch_github": "succeeded",
                "fetch_arxiv": "failed",
            }
        },
    )

    result = outcome.outputs["join_result"]
    assert result["ready"] is True
    assert result["decision"] == "joined"


def test_join_quorum_passes_when_threshold_met() -> None:
    outcome = _join_outcome(
        metadata={
            "join_policy": "quorum",
            "required_upstream_step_ids": ["a", "b", "c"],
            "quorum": 2,
        },
        inputs={
            "upstream_statuses": {
                "a": "succeeded",
                "b": "succeeded",
                "c": "failed",
            }
        },
    )

    result = outcome.outputs["join_result"]
    assert result["ready"] is True
    assert result["quorum"] == 2
    assert result["succeeded_upstreams"] == ["a", "b"]


def test_join_best_effort_passes_with_partial_results() -> None:
    outcome = _join_outcome(
        metadata={
            "join_policy": "best_effort",
            "required_upstream_step_ids": ["a", "b"],
        },
        inputs={"upstream_statuses": {"a": "succeeded", "b": "failed"}},
    )

    result = outcome.outputs["join_result"]
    assert result["ready"] is True
    assert result["decision"] == "joined"
    assert result["failed_upstreams"] == ["b"]


def test_timeout_join_fails_when_timeout_exceeded_and_on_timeout_fail() -> None:
    outcome = _join_outcome(
        metadata={
            "join_policy": "timeout_join",
            "required_upstream_step_ids": ["a", "b"],
            "timeout_seconds": 1,
            "on_timeout": "fail",
            "join_wait_started_at": (
                datetime.now(UTC) - timedelta(seconds=5)
            ).isoformat().replace("+00:00", "Z"),
        },
        inputs={"upstream_statuses": {"a": "succeeded"}},
    )

    result = outcome.outputs["join_result"]
    assert result["ready"] is False
    assert result["decision"] == "timeout"
    assert result["timed_out"] is True


def test_timeout_join_best_effort_when_timeout_exceeded() -> None:
    outcome = _join_outcome(
        metadata={
            "join_policy": "timeout_join",
            "required_upstream_step_ids": ["a", "b"],
            "timeout_seconds": 1,
            "on_timeout": "best_effort",
            "join_wait_started_at": (
                datetime.now(UTC) - timedelta(seconds=5)
            ).isoformat().replace("+00:00", "Z"),
        },
        inputs={"upstream_statuses": {"a": "succeeded"}},
    )

    result = outcome.outputs["join_result"]
    assert result["ready"] is True
    assert result["decision"] == "partial_join"
    assert result["timed_out"] is True


def test_join_is_not_scheduled_until_required_upstreams_complete(tmp_path) -> None:
    functions = FunctionStepRegistry()
    functions.register("source", lambda buffer: {"start": True})
    functions.register("left", lambda buffer: {"left_status": "succeeded"})
    functions.register("right", lambda buffer: {"right_status": "succeeded"})
    registry = StepRunnerRegistry.with_function_runner(FunctionStepRunner(functions))
    registry.register(StepType.JOIN, JoinStepRunner())

    result = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path),
    ).execute(_fanout_join_workflow(), {}, profile="test", run_id="run-join-waits")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.path == ["source", "left", "right", "join"]
    assert result.path.count("join") == 1
    assert result.output["join_result"]["ready"] is False
    assert result.output["join_result"]["decision"] == "waiting"


def test_join_is_scheduled_once_after_all_required_upstreams_complete(tmp_path) -> None:
    functions = FunctionStepRegistry()
    functions.register("source", lambda buffer: {"start": True})
    functions.register("left", lambda buffer: {"left_status": "succeeded"})
    functions.register("right", lambda buffer: {"right_status": "succeeded"})
    registry = StepRunnerRegistry.with_function_runner(FunctionStepRunner(functions))
    registry.register(StepType.JOIN, JoinStepRunner())

    result = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path),
    ).execute(_fanout_join_workflow(), {}, profile="test", run_id="run-join-once")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.path.count("join") == 1


def _fanout_join_workflow() -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="join-executor",
        name="Join Executor",
        version="1.0",
        start_step_id="source",
        steps=[
            StepSpec("source", "source", write_keys=["start"]),
            StepSpec("left", "left", read_keys=["start"], write_keys=["left_status"]),
            StepSpec("right", "right", read_keys=["start"], write_keys=["right_status"]),
            StepSpec(
                "join",
                "join.inputs",
                step_type=StepType.JOIN,
                read_keys=[],
                write_keys=["join_result"],
                required_output_keys=["join_result"],
                metadata={
                    "join_policy": "all_success",
                    "required_upstream_step_ids": ["left", "right"],
                },
            ),
        ],
        edges=[
            EdgeSpec("source-left", "source", "left"),
            EdgeSpec("source-right", "source", "right"),
            EdgeSpec("left-join", "left", "join"),
            EdgeSpec("right-join", "right", "join"),
        ],
    )
