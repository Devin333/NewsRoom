import json

import pytest

from core.framework.artifacts import ArtifactManager
from core.framework.agent_loop import AgentLoopResult, AgentLoopStatus, AgentRunner, AgentSpec
from core.framework.events import EventBus
from core.framework.llm import (
    FakeLLMClient,
    GlobalBudgetPolicy,
    GlobalBudgetTracker,
    LLMResponse,
    REDACTED_VALUE,
)
from core.framework.specs import (
    ArtifactPolicySpec,
    EdgeSpec,
    QualityPolicySpec,
    ResourcePolicySpec,
    StepSpec,
    StepStatus,
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
    build_default_step_runner_registry,
)
from storage.conversation import LocalJsonConversationStore


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
    assert result.step_results["validate"].metrics["tool_name"] == "report.validate"
    assert result.step_results["validate"].metrics["tool_status"] == "succeeded"
    assert result.step_results["validate"].metrics["approval_required"] is False


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


def test_agent_loop_step_runner_writes_conversation_cursor_context(tmp_path) -> None:
    conversation_store = LocalJsonConversationStore(tmp_path / "conversations")
    agent = AgentSpec(
        agent_id="analyst",
        name="Analyst",
        role="Analyze",
        goal="Produce analysis",
        instructions="Return JSON actions only.",
        input_keys=["request"],
        output_key="analysis_result",
    )
    runner = AgentLoopStepRunner(
        AgentRunner(
            llm_client=FakeLLMClient(
                ['{"action_type":"final_output","output":{"analysis_result":{"summary":"ok"}}}']
            ),
            tool_registry=ToolRegistry(),
            conversation_store=conversation_store,
        ),
        {"analyst": agent},
    )
    registry = StepRunnerRegistry()
    registry.register(StepType.AGENT_LOOP, runner)
    spec = WorkflowSpec(
        workflow_id="agent-loop-cursor",
        name="Agent Loop Cursor",
        version="1.0",
        start_step_id="agent",
        steps=[
            StepSpec(
                step_id="agent",
                implementation="analyst",
                step_type=StepType.AGENT_LOOP,
                read_keys=["request"],
                write_keys=["analysis_result"],
                required_output_keys=["analysis_result"],
                metadata={
                    "conversation_id": "conversation-workflow",
                    "workflow_checkpoint_id": "cp-workflow",
                },
            )
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path / "runs"),
    )

    result = executor.execute(
        spec,
        {"topic": "chips"},
        profile="test",
        run_id="run-agent-cursor",
    )
    cursor = conversation_store.read_cursor("conversation-workflow")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert cursor is not None
    assert cursor.run_id == "run-agent-cursor"
    assert cursor.step_id == "agent"
    assert cursor.workflow_checkpoint_id == "cp-workflow"
    assert cursor.metadata["agent_id"] == "analyst"


def test_agent_loop_step_runner_passes_cursor_resume_flag() -> None:
    agent_result = AgentLoopResult(
        success=True,
        status=AgentLoopStatus.ACCEPTED,
        output={"analysis": {"summary": "ok"}},
    )
    fake_runner = _FakeAgentRunner(agent_result)
    runner = AgentLoopStepRunner(fake_runner, {"analyst": object()})
    buffer = DataBuffer({"request": {"topic": "ai"}})

    outcome = runner.run(
        StepSpec(
            step_id="agent",
            implementation="analyst",
            step_type=StepType.AGENT_LOOP,
            read_keys=["request"],
            write_keys=["analysis"],
            metadata={
                "conversation_id": "conversation-1",
                "resume_from_conversation_cursor": True,
            },
        ),
        buffer.scope(read_keys=["request"], write_keys=["analysis"]),
    )

    assert outcome.status == StepStatus.SUCCEEDED
    assert fake_runner.calls[-1]["kwargs"]["conversation_id"] == "conversation-1"
    assert fake_runner.calls[-1]["kwargs"]["resume_from_cursor"] is True


def test_agent_loop_step_runner_writes_redacted_llm_call_artifacts(tmp_path) -> None:
    fake_secret = "sk" + "-abcdef1234567890"
    agent = AgentSpec(
        agent_id="analyst",
        name="Analyst",
        role="Analyze",
        goal="Produce analysis",
        instructions="Return JSON actions only.",
        input_keys=["request"],
        output_key="analysis_result",
    )
    runner = AgentLoopStepRunner(
        AgentRunner(
            llm_client=FakeLLMClient(
                [
                    LLMResponse(
                        content=(
                            '{"action_type":"final_output",'
                            '"output":{"analysis_result":{"summary":"ok"}}}'
                        ),
                        metadata={
                            "provider": "fake",
                            "model": "fake-llm",
                            "api_key": fake_secret,
                        },
                    )
                ]
            ),
            tool_registry=ToolRegistry(),
        ),
        {"analyst": agent},
    )
    registry = StepRunnerRegistry()
    registry.register(StepType.AGENT_LOOP, runner)
    spec = WorkflowSpec(
        workflow_id="agent-loop-llm-artifacts",
        name="Agent Loop LLM Artifacts",
        version="1.0",
        start_step_id="agent",
        steps=[
            StepSpec(
                step_id="agent",
                implementation="analyst",
                step_type=StepType.AGENT_LOOP,
                read_keys=["request"],
                write_keys=["analysis_result", "llm_call_artifacts"],
                required_output_keys=["analysis_result", "llm_call_artifacts"],
            )
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(
        spec,
        {"topic": fake_secret},
        profile="test",
        run_id="run-agent-llm-artifacts",
    )

    run_dir = tmp_path / "run-agent-llm-artifacts"
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    llm_artifact = json.loads((run_dir / "llm_calls" / "agent_001.json").read_text(encoding="utf-8"))
    step_results = json.loads((run_dir / "step_results.json").read_text(encoding="utf-8"))
    step_artifacts = manifest["step_artifacts"]
    llm_refs = [item for item in step_artifacts if item["artifact_type"] == "llm_call"]

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["llm_call_artifacts"][0]["artifact_id"] == "analyst:llm_call:1"
    assert (
        step_results["agent"]["outputs"]["llm_call_artifacts"][0]["artifact_ref"]["path"]
        == "llm_calls/agent_001.json"
    )
    assert manifest["artifacts"]["step.agent.llm_call.analyst:llm_call:1"] == "llm_calls/agent_001.json"
    assert llm_refs[0]["redacted"] is True
    assert llm_artifact["request"]["messages"][1]["content"].find(fake_secret) == -1
    assert llm_artifact["response"]["metadata"]["api_key"] == REDACTED_VALUE
    assert fake_secret not in (run_dir / "llm_calls" / "agent_001.json").read_text(encoding="utf-8")


def test_agent_loop_step_runner_marks_global_budget_exceeded(tmp_path) -> None:
    agent = AgentSpec(
        agent_id="analyst",
        name="Analyst",
        role="Analyze",
        goal="Produce analysis",
        instructions="Return JSON actions only.",
        input_keys=["request"],
        output_key="analysis_result",
    )
    runner = AgentLoopStepRunner(
        AgentRunner(
            llm_client=FakeLLMClient(
                [
                    '{"action_type":"final_output","output":{"wrong_key":{"summary":"missing"}}}',
                    '{"action_type":"final_output","output":{"analysis_result":{"summary":"ok"}}}',
                ]
            ),
            tool_registry=ToolRegistry(),
        ),
        {"analyst": agent},
        global_budget_tracker=GlobalBudgetTracker(GlobalBudgetPolicy(max_llm_calls=1)),
    )
    registry = StepRunnerRegistry()
    registry.register(StepType.AGENT_LOOP, runner)
    spec = WorkflowSpec(
        workflow_id="agent-loop-budget",
        name="Agent Loop Budget",
        version="1.0",
        start_step_id="agent",
        steps=[
            StepSpec(
                step_id="agent",
                implementation="analyst",
                step_type=StepType.AGENT_LOOP,
                read_keys=["request"],
                write_keys=["agent_loop_result", "agent_loop_metrics"],
            )
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(spec, {"topic": "chips"}, profile="test", run_id="run-agent-budget")

    assert result.status == WorkflowStatus.BUDGET_EXCEEDED
    assert result.error is not None
    assert result.error.details["budget_exceeded"] is True
    assert result.error.details["global_budget_check"]["violations"] == ["max_llm_calls"]
    assert result.manifest["metrics"]["global_budget_usage"]["llm_calls"] == 2


def test_agent_loop_step_runner_writes_diagnostics_artifact_for_blocked_run(tmp_path) -> None:
    fake_secret = "sk" + "-abcdef1234567890"
    agent = AgentSpec(
        agent_id="analyst",
        name="Analyst",
        role="Analyze",
        goal="Produce analysis",
        instructions="Return JSON actions only.",
        input_keys=["request"],
        output_key="analysis_result",
    )
    runner = AgentLoopStepRunner(
        AgentRunner(
            llm_client=FakeLLMClient(
                [
                    (
                        '{"action_type":"final_output",'
                        '"output":{"analysis_result":{"secret":"'
                        + fake_secret
                        + '"}}}'
                    )
                ]
            ),
            tool_registry=ToolRegistry(),
        ),
        {"analyst": agent},
    )
    registry = StepRunnerRegistry()
    registry.register(StepType.AGENT_LOOP, runner)
    spec = WorkflowSpec(
        workflow_id="agent-loop-blocked",
        name="Agent Loop Blocked",
        version="1.0",
        start_step_id="agent",
        steps=[
            StepSpec(
                step_id="agent",
                implementation="analyst",
                step_type=StepType.AGENT_LOOP,
                read_keys=["request"],
                write_keys=[
                    "agent_loop_result",
                    "agent_loop_events",
                    "agent_loop_metrics",
                    "agent_loop_diagnostics",
                    "agent_loop_trace",
                ],
            )
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(spec, {"topic": "chips"}, profile="test", run_id="run-agent-blocked")

    run_dir = tmp_path / "run-agent-blocked"
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    diagnostics = json.loads((run_dir / "agent_loop_diagnostics.json").read_text(encoding="utf-8"))

    assert result.status == WorkflowStatus.BLOCKED
    assert result.output["agent_loop_diagnostics"]["stop_reason"] == "secret_blocked"
    assert manifest["artifacts"]["agent_loop_diagnostics"] == "agent_loop_diagnostics.json"
    assert manifest["artifacts"]["agent_loop_trace"] == "agent_loop_trace.json"
    assert manifest["agent_loop_metrics"]["llm_calls"] == 1
    assert manifest["llm_calls"] == 1
    assert diagnostics["severity"] == "blocked"


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
    assert result.step_results["parallel"].metrics["branch_count"] == 2
    assert result.step_results["parallel"].metrics["conflict_strategy"] == "merge_list"
    assert result.step_results["parallel"].metrics["output_keys"] == ["items"]


def test_parallel_group_step_runner_reports_output_conflicts() -> None:
    functions = FunctionStepRegistry()
    functions.register("branch.left", lambda buffer: {"item": "left"})
    functions.register("branch.right", lambda buffer: {"item": "right"})
    runner = ParallelGroupStepRunner(functions, max_workers=2)
    buffer = DataBuffer()
    step = StepSpec(
        step_id="parallel",
        implementation="parallel.conflict",
        step_type=StepType.PARALLEL_GROUP,
        write_keys=["item"],
        metadata={
            "branches": [
                {"branch_id": "left", "implementation": "branch.left", "write_keys": ["item"]},
                {"branch_id": "right", "implementation": "branch.right", "write_keys": ["item"]},
            ],
        },
    )

    outcome = runner.run(step, buffer.scope(read_keys=[], write_keys=["item"]))

    assert outcome.status == StepStatus.FAILED
    assert outcome.error_type == "StepExecutionError"
    assert "output conflict" in outcome.error_message


def test_parallel_group_step_runner_merges_dict_outputs_and_branch_results() -> None:
    functions = FunctionStepRegistry()
    functions.register("branch.left", lambda buffer: {"items": {"left": 1}})
    functions.register("branch.right", lambda buffer: {"items": {"right": 2}})
    runner = ParallelGroupStepRunner(functions, max_workers=2)
    buffer = DataBuffer()

    outcome = runner.run(
        StepSpec(
            step_id="parallel",
            implementation="parallel.merge",
            step_type=StepType.PARALLEL_GROUP,
            write_keys=["items", "branch_results"],
            required_output_keys=["items"],
            metadata={
                "conflict_strategy": "merge_dict",
                "branch_results_key": "branch_results",
                "branches": [
                    {
                        "branch_id": "left",
                        "implementation": "branch.left",
                        "write_keys": ["items"],
                        "required_output_keys": ["items"],
                    },
                    {
                        "branch_id": "right",
                        "implementation": "branch.right",
                        "write_keys": ["items"],
                        "required_output_keys": ["items"],
                    },
                ],
            },
        ),
        buffer.scope(read_keys=[], write_keys=["items", "branch_results"]),
    )

    assert outcome.status == StepStatus.SUCCEEDED
    assert buffer.read("items") == {"left": 1, "right": 2}
    assert {result["branch_id"] for result in buffer.read("branch_results")} == {
        "left",
        "right",
    }
    assert outcome.metrics["branch_count"] == 2
    assert outcome.metrics["output_key_count"] == 2


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
    assert result.step_results["child"].metrics["child_run_id"] == "run-parent.child.child"
    assert result.step_results["child"].metrics["child_workflow_id"] == "child"
    assert result.step_results["child"].metrics["child_status"] == "succeeded"
    assert result.step_results["child"].metrics["child_step_count"] == 1


def test_subworkflow_step_runner_returns_failed_outcome_when_child_fails(tmp_path) -> None:
    functions = FunctionStepRegistry()
    functions.register(
        "child.fail",
        lambda buffer: (_ for _ in ()).throw(RuntimeError("child failed")),
    )
    registry = StepRunnerRegistry.with_function_runner(FunctionStepRunner(functions))
    child = WorkflowSpec(
        workflow_id="child",
        name="Child",
        version="1.0",
        start_step_id="fail",
        steps=[
            StepSpec(
                step_id="fail",
                implementation="child.fail",
                write_keys=["echo"],
            )
        ],
    )
    registry.register(StepType.SUBWORKFLOW, SubworkflowStepRunner({"child": child}, registry))
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
                write_keys=["subworkflow_result"],
                metadata={"workflow_id": "child", "request": {}},
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
    assert result.step_results["child"].metrics["child_workflow_id"] == "child"


def test_tool_call_and_tool_batch_steps_route_to_next_steps(tmp_path) -> None:
    functions = FunctionStepRegistry()
    functions.register(
        "route.after_call",
        lambda buffer: {"call_routed": buffer.read("validate_tool_result")["output"]["valid"]},
    )
    functions.register(
        "route.after_batch",
        lambda buffer: {"batch_routed": len(buffer.read("tool_results"))},
    )
    registry = build_default_step_runner_registry(
        functions,
        tool_registry=build_builtin_tool_registry(include_network_tools=False),
    )
    spec = WorkflowSpec(
        workflow_id="tool-routing",
        name="Tool Routing",
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
            ),
            StepSpec(
                step_id="after_call",
                implementation="route.after_call",
                read_keys=["validate_tool_result"],
                write_keys=["call_routed"],
                required_output_keys=["call_routed"],
            ),
            StepSpec(
                step_id="tools",
                implementation="tools.batch",
                step_type=StepType.TOOL_BATCH,
                write_keys=["tool_observations", "tool_results"],
                required_output_keys=["tool_observations", "tool_results"],
                metadata={
                    "tool_policy": {"allowed_tools": ["quality.duplicate_check"]},
                    "tool_calls": [
                        {
                            "tool_name": "quality.duplicate_check",
                            "call_id": "dedup-items",
                            "arguments": {
                                "items": [
                                    {"title": "Same", "url": "https://example.com/a"},
                                    {"title": "Same", "url": "https://example.com/a"},
                                ]
                            },
                        }
                    ],
                },
            ),
            StepSpec(
                step_id="after_batch",
                implementation="route.after_batch",
                read_keys=["tool_results"],
                write_keys=["batch_routed"],
                required_output_keys=["batch_routed"],
            ),
        ],
        edges=[
            EdgeSpec("validate-to-after-call", "validate", "after_call"),
            EdgeSpec("after-call-to-tools", "after_call", "tools"),
            EdgeSpec("tools-to-after-batch", "tools", "after_batch"),
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(spec, {}, profile="test", run_id="run-tool-routing")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.path == ["validate", "after_call", "tools", "after_batch"]
    assert result.output["call_routed"] is True
    assert result.output["batch_routed"] == 1
    assert result.step_results["validate"].metrics["tool_status"] == "succeeded"
    assert result.step_results["tools"].metrics["tool_call_count"] == 1
    assert result.step_results["tools"].metrics["succeeded_count"] == 1


def test_agent_loop_step_runner_maps_fake_runner_statuses() -> None:
    cases = [
        (
            AgentLoopResult(
                success=True,
                status=AgentLoopStatus.ACCEPTED,
                output={"analysis": {"summary": "ok"}},
            ),
            StepStatus.SUCCEEDED,
            None,
        ),
        (
            AgentLoopResult(
                success=False,
                status=AgentLoopStatus.BLOCKED,
                error="policy blocked",
            ),
            StepStatus.BLOCKED,
            "AgentLoopBlocked",
        ),
        (
            AgentLoopResult(
                success=False,
                status=AgentLoopStatus.WAITING_FOR_APPROVAL,
                error="approval required",
            ),
            StepStatus.PAUSED,
            "AgentLoopWaitingForApproval",
        ),
        (
            AgentLoopResult(
                success=False,
                status=AgentLoopStatus.STALLED,
                error="repeated tool call",
            ),
            StepStatus.BLOCKED,
            "AgentLoopStalled",
        ),
        (
            AgentLoopResult(
                success=False,
                status=AgentLoopStatus.FAILED,
                error="loop failed",
            ),
            StepStatus.FAILED,
            "AgentLoopFailed",
        ),
    ]
    step = StepSpec(
        step_id="agent",
        implementation="analyst",
        step_type=StepType.AGENT_LOOP,
        read_keys=["request"],
        write_keys=["analysis", "agent_loop_result", "agent_loop_events", "agent_loop_metrics"],
    )

    for agent_result, expected_status, expected_error_type in cases:
        buffer = DataBuffer({"request": {"topic": "ai"}})
        runner = AgentLoopStepRunner(_FakeAgentRunner(agent_result), {"analyst": object()})

        outcome = runner.run(
            step,
            buffer.scope(
                read_keys=["request"],
                write_keys=[
                    "analysis",
                    "agent_loop_result",
                    "agent_loop_events",
                    "agent_loop_metrics",
                ],
            ),
        )

        assert outcome.status == expected_status
        assert outcome.error_type == expected_error_type
        assert buffer.read("agent_loop_result")["status"] == agent_result.status.value


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


class _FakeAgentRunner:
    def __init__(self, result: AgentLoopResult) -> None:
        self._result = result
        self.calls = []

    def run(self, agent, inputs, *, conversation_id=None, **kwargs):
        self.calls.append(
            {
                "agent": agent,
                "inputs": inputs,
                "kwargs": {"conversation_id": conversation_id, **kwargs},
            }
        )
        return self._result
