import json

from core.framework.artifacts import ArtifactManager
from core.framework.agent_loop import AgentRunner, AgentSpec
from core.framework.events import EventBus
from core.framework.llm import FakeLLMClient
from core.framework.specs import (
    ArtifactPolicySpec,
    EdgeSpec,
    QualityPolicySpec,
    ResourcePolicySpec,
    StepSpec,
    StepType,
    WorkflowSpec,
    WorkflowStatus,
)
from core.framework.tools import ToolDefinition, ToolRegistry, build_builtin_tool_registry
from core.framework.workflow import (
    AgentLoopStepRunner,
    ArtifactStepRunner,
    DataBuffer,
    FunctionStepRegistry,
    FunctionStepRunner,
    HumanReviewStepRunner,
    JoinStepRunner,
    ParallelGroupStepRunner,
    QualityGateStepRunner,
    RouterStepRunner,
    StepRunnerRegistry,
    SubworkflowStepRunner,
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


def test_agent_loop_step_runner_executes_registered_agent(tmp_path) -> None:
    tool_registry = ToolRegistry()
    tool_registry.register(
        ToolDefinition(name="memory.search", input_schema={"required": ["query"]}),
        lambda args: {"matches": [{"title": args["query"], "source": "fixture"}]},
    )
    agent = AgentSpec(
        agent_id="analyst",
        name="Analyst",
        role="Analyze",
        goal="Produce analysis",
        instructions="Return JSON actions only.",
        input_keys=["request"],
        output_key="analysis_result",
        allowed_tools=["memory.search"],
    )
    runner = AgentLoopStepRunner(
        AgentRunner(
            llm_client=FakeLLMClient(
                [
                    (
                        '{"action_type":"tool_call","tool_name":"memory.search",'
                        '"tool_args":{"query":"chips"}}'
                    ),
                    (
                        '{"action_type":"final_output",'
                        '"output":{"analysis_result":{"summary":"ok"}}}'
                    ),
                ]
            ),
            tool_registry=tool_registry,
        ),
        {"analyst": agent},
    )
    registry = StepRunnerRegistry()
    registry.register(StepType.AGENT_LOOP, runner)
    spec = WorkflowSpec(
        workflow_id="agent-loop-step",
        name="Agent Loop Step",
        version="1.0",
        start_step_id="agent",
        steps=[
            StepSpec(
                step_id="agent",
                implementation="analyst",
                step_type=StepType.AGENT_LOOP,
                read_keys=["request"],
                write_keys=[
                    "analysis_result",
                    "agent_loop_result",
                    "agent_loop_events",
                    "agent_loop_metrics",
                ],
                required_output_keys=[
                    "analysis_result",
                    "agent_loop_result",
                    "agent_loop_events",
                    "agent_loop_metrics",
                ],
            )
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(spec, {"topic": "chips"}, profile="test", run_id="run-agent-step")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["analysis_result"]["summary"] == "ok"
    assert result.output["agent_loop_metrics"]["llm_calls"] == 2
    assert result.output["agent_loop_metrics"]["tool_calls"] == 1


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


def test_parallel_group_step_runner_merges_real_branch_outputs(tmp_path) -> None:
    functions = FunctionStepRegistry()
    functions.register("branch.left", lambda buffer: {"items": ["left", buffer.read("request")["topic"]]})
    functions.register("branch.right", lambda buffer: {"items": ["right"]})
    registry = StepRunnerRegistry()
    registry.register(StepType.PARALLEL_GROUP, ParallelGroupStepRunner(functions))
    spec = WorkflowSpec(
        workflow_id="parallel-group",
        name="Parallel Group",
        version="1.0",
        start_step_id="parallel",
        steps=[
            StepSpec(
                step_id="parallel",
                implementation="parallel.sources",
                step_type=StepType.PARALLEL_GROUP,
                read_keys=["request"],
                write_keys=["items"],
                required_output_keys=["items"],
                metadata={
                    "conflict_strategy": "merge_list",
                    "branches": [
                        {
                            "branch_id": "left",
                            "implementation": "branch.left",
                            "read_keys": ["request"],
                            "write_keys": ["items"],
                            "required_output_keys": ["items"],
                        },
                        {
                            "branch_id": "right",
                            "implementation": "branch.right",
                            "read_keys": ["request"],
                            "write_keys": ["items"],
                            "required_output_keys": ["items"],
                        },
                    ],
                },
            )
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(spec, {"topic": "ai"}, profile="test", run_id="run-parallel")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert sorted(result.output["items"]) == ["ai", "left", "right"]


def test_subworkflow_step_runner_executes_child_workflow(tmp_path) -> None:
    functions = FunctionStepRegistry()
    functions.register("child.echo", lambda buffer: {"echo": buffer.read("request")["topic"]})
    registry = StepRunnerRegistry.with_function_runner(FunctionStepRunner(functions))
    child = WorkflowSpec(
        workflow_id="child",
        name="Child",
        version="1.0",
        start_step_id="echo",
        steps=[
            StepSpec(
                step_id="echo",
                implementation="child.echo",
                read_keys=["request"],
                write_keys=["echo"],
                required_output_keys=["echo"],
            )
        ],
    )
    registry.register(
        StepType.SUBWORKFLOW,
        SubworkflowStepRunner({"child": child}, registry),
    )
    parent = WorkflowSpec(
        workflow_id="parent",
        name="Parent",
        version="1.0",
        start_step_id="child",
        steps=[
            StepSpec(
                step_id="child",
                implementation="child",
                step_type=StepType.SUBWORKFLOW,
                read_keys=["request"],
                write_keys=["subworkflow_result"],
                required_output_keys=["subworkflow_result"],
                metadata={"workflow_id": "child", "request_key": "request"},
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
    assert result.output["subworkflow_result"]["output"]["echo"] == "ai"
    assert (tmp_path / "run-parent.child.child" / "manifest.json").exists()


def test_executor_publishes_event_bus_blocks_resource_and_writes_policy_artifacts(tmp_path) -> None:
    events = []
    event_bus = EventBus()
    event_bus.subscribe(events.append)
    functions = FunctionStepRegistry()
    functions.register("sample.count", lambda buffer: {"count": len(buffer.read("request")["items"])})
    registry = StepRunnerRegistry.with_function_runner(FunctionStepRunner(functions))
    spec = WorkflowSpec(
        workflow_id="policy-artifacts",
        name="Policy Artifacts",
        version="1.0",
        start_step_id="count",
        steps=[
            StepSpec(
                step_id="count",
                implementation="sample.count",
                read_keys=["request"],
                write_keys=["count"],
                required_output_keys=["count"],
                resource_policy=ResourcePolicySpec(max_items=1),
                artifact_policy=ArtifactPolicySpec(
                    write_step_input=True,
                    write_step_output=True,
                    write_step_error=True,
                ),
            )
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path),
        event_bus=event_bus,
    )

    result = executor.execute(
        spec,
        {"items": ["a", "b"]},
        profile="test",
        run_id="run-policy-artifacts",
    )

    assert result.status == WorkflowStatus.BLOCKED
    assert result.error.error_type == "WorkflowResourcePolicyViolation"
    assert [event.event_type for event in events][:2] == ["workflow_started", "step_started"]
    assert "policy_violation" in [event.event_type for event in events]
    run_dir = tmp_path / "run-policy-artifacts"
    assert (run_dir / "steps" / "count" / "input.json").exists()
    assert (run_dir / "steps" / "count" / "error.json").exists()
