import json

from core.framework.artifacts import ArtifactManager
from core.framework.specs import (
    EdgeSpec,
    QualityPolicySpec,
    StepSpec,
    StepType,
    WorkflowSpec,
    WorkflowStatus,
)
from core.framework.tools import build_builtin_tool_registry
from core.framework.workflow import (
    ArtifactStepRunner,
    DataBuffer,
    HumanReviewStepRunner,
    JoinStepRunner,
    QualityGateStepRunner,
    RouterStepRunner,
    StepRunnerRegistry,
    ToolCallStepRunner,
    WorkflowExecutor,
)


def test_tool_call_step_runner_executes_real_tool(tmp_path) -> None:
    registry = StepRunnerRegistry()
    registry.register(
        StepType.TOOL_CALL,
        ToolCallStepRunner(build_builtin_tool_registry(include_network_tools=False)),
    )
    spec = WorkflowSpec(
        workflow_id="tool-call",
        name="Tool Call",
        version="1.0",
        start_step_id="validate",
        steps=[
            StepSpec(
                step_id="validate",
                implementation="tools.call",
                step_type=StepType.TOOL_CALL,
                write_keys=["validate_tool_observation", "validate_tool_result"],
                required_output_keys=["validate_tool_observation", "validate_tool_result"],
                metadata={
                    "tool_name": "report.validate",
                    "arguments": {
                        "report": {
                            "title": "Daily Brief",
                            "sections": [{"content": "Supported update"}],
                            "source_urls": ["https://example.com/source"],
                        }
                    },
                    "tool_policy": {"allowed_tools": ["report.validate"]},
                },
            )
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(spec, {}, profile="test", run_id="run-tool-call")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["validate_tool_result"]["status"] == "succeeded"
    assert result.output["validate_tool_result"]["output"]["valid"] is True


def test_artifact_step_runner_writes_real_artifact(tmp_path) -> None:
    registry = StepRunnerRegistry()
    registry.register(StepType.ARTIFACT, ArtifactStepRunner())
    spec = WorkflowSpec(
        workflow_id="artifact-step",
        name="Artifact Step",
        version="1.0",
        start_step_id="artifact",
        steps=[
            StepSpec(
                step_id="artifact",
                implementation="artifact.write",
                step_type=StepType.ARTIFACT,
                write_keys=["artifact_ref"],
                required_output_keys=["artifact_ref"],
                metadata={
                    "content": {"report": "ready"},
                    "relative_path": "steps/artifact/output.json",
                    "artifact_id": "artifact-output",
                },
            )
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(spec, {}, profile="test", run_id="run-artifact-step")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["artifact_ref"]["artifact_id"] == "artifact-output"
    assert (tmp_path / "run-artifact-step" / "steps" / "artifact" / "output.json").exists()
    manifest = json.loads((tmp_path / "run-artifact-step" / "manifest.json").read_text())
    assert manifest["artifacts"]["step.artifact.step_output.artifact-output"] == (
        "steps/artifact/output.json"
    )


def test_quality_gate_and_join_runners_execute(tmp_path) -> None:
    registry = StepRunnerRegistry()
    registry.register(StepType.QUALITY_GATE, QualityGateStepRunner())
    registry.register(StepType.JOIN, JoinStepRunner())
    spec = WorkflowSpec(
        workflow_id="quality-join",
        name="Quality Join",
        version="1.0",
        start_step_id="gate",
        steps=[
            StepSpec(
                step_id="gate",
                implementation="quality.gate",
                step_type=StepType.QUALITY_GATE,
                read_keys=["request"],
                write_keys=["quality_gate_metrics"],
                required_output_keys=["quality_gate_metrics"],
                quality_policy=QualityPolicySpec(min_editor_score=0.9),
                metadata={"editor_score_key": "editor_score"},
            ),
            StepSpec(
                step_id="join",
                implementation="join.inputs",
                step_type=StepType.JOIN,
                read_keys=["quality_gate_metrics"],
                write_keys=["join_result"],
                required_output_keys=["join_result"],
            ),
        ],
        edges=[EdgeSpec("gate-to-join", "gate", "join")],
    )
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(spec, {"topic": "ai"}, profile="test", run_id="run-quality-join")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["quality_gate_metrics"]["decision"] == "rewrite_required"
    assert result.output["join_result"]["joined_keys"] == ["quality_gate_metrics"]


def test_router_runner_returns_next_hint() -> None:
    runner = RouterStepRunner()
    buffer = DataBuffer({"route": "publish"})
    outcome = runner.run(
        StepSpec(
            step_id="router",
            implementation="router.route",
            step_type=StepType.ROUTER,
            read_keys=["route"],
            write_keys=["selected_route"],
            metadata={"output_key": "selected_route"},
        ),
        buffer.scope(read_keys=["route"], write_keys=["selected_route"]),
    )

    assert outcome.next_hint == "publish"
    assert buffer.read("selected_route") == "publish"


def test_human_review_runner_pauses_workflow(tmp_path) -> None:
    registry = StepRunnerRegistry()
    registry.register(StepType.HUMAN_REVIEW, HumanReviewStepRunner())
    review_step = StepSpec(
        step_id="review",
        implementation="human.review",
        step_type=StepType.HUMAN_REVIEW,
        read_keys=["request"],
        write_keys=["human_review_request"],
        required_output_keys=["human_review_request"],
    )
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path),
    )

    pause_result = executor.execute(
        WorkflowSpec(
            workflow_id="human-only",
            name="Human Only",
            version="1.0",
            start_step_id="review",
            steps=[review_step],
        ),
        {"topic": "ai"},
        profile="test",
        run_id="run-human-runner",
    )

    assert pause_result.status == WorkflowStatus.WAITING_FOR_HUMAN
    assert pause_result.output["human_review_request"]["inputs"]["request"]["topic"] == "ai"
