import pytest

from core.framework.specs import StepSpec, StepStatus, StepType, WorkflowSpec
from framework.tool import ToolRegistry
from core.framework.workflow import (
    DataBuffer,
    FunctionStepRegistry,
    FunctionStepRunner,
    StepExecutionError,
    StepOutcome,
    StepRunnerRegistry,
    build_default_step_runner_registry,
)


def test_function_step_runner_writes_returned_outputs() -> None:
    registry = FunctionStepRegistry()
    registry.register("sample.plan", lambda buffer: {"plan": {"topic": buffer.read("request")["topic"]}})
    runner = FunctionStepRunner(registry)
    buffer = DataBuffer({"request": {"topic": "markets"}})
    scoped = buffer.scope(read_keys=["request"], write_keys=["plan"])

    outcome = runner.run(
        StepSpec(
            step_id="plan",
            implementation="sample.plan",
            read_keys=["request"],
            write_keys=["plan"],
            required_output_keys=["plan"],
        ),
        scoped,
    )

    assert outcome.status == "succeeded"
    assert buffer.read("plan") == {"topic": "markets"}


def test_function_step_runner_rejects_missing_required_output() -> None:
    registry = FunctionStepRegistry()
    registry.register("sample.empty", lambda buffer: {})
    runner = FunctionStepRunner(registry)
    buffer = DataBuffer()

    outcome = runner.run(
        StepSpec(
            step_id="empty",
            implementation="sample.empty",
            write_keys=["plan"],
            required_output_keys=["plan"],
        ),
        buffer.scope(read_keys=[], write_keys=["plan"]),
    )

    assert outcome.status == StepStatus.FAILED
    assert outcome.error_type == "StepExecutionError"
    assert "required output keys" in outcome.error_message


def test_function_step_runner_rejects_unregistered_function() -> None:
    runner = FunctionStepRunner(FunctionStepRegistry())

    outcome = runner.run(
        StepSpec(step_id="missing", implementation="sample.missing"),
        DataBuffer().scope(read_keys=[], write_keys=[]),
    )

    assert outcome.status == StepStatus.FAILED
    assert outcome.error_type == "StepExecutionError"
    assert "not registered" in outcome.error_message


def test_step_runner_registry_returns_registered_runner() -> None:
    runner = _CustomRunner()
    registry = StepRunnerRegistry()

    registry.register(StepType.ARTIFACT, runner)

    assert registry.is_registered(StepType.ARTIFACT)
    assert not registry.is_registered(StepType.PERSIST)
    assert registry.get("artifact") is runner
    assert registry.registered_step_types() == [StepType.ARTIFACT]
    assert registry.missing_step_types([StepType.ARTIFACT, StepType.PERSIST]) == [StepType.PERSIST]


def test_step_runner_registry_rejects_duplicate_registration() -> None:
    registry = StepRunnerRegistry()
    registry.register(StepType.ARTIFACT, _CustomRunner())

    with pytest.raises(StepExecutionError, match="already registered"):
        registry.register(StepType.ARTIFACT, _CustomRunner())


def test_step_runner_registry_rejects_missing_runner() -> None:
    registry = StepRunnerRegistry()

    with pytest.raises(StepExecutionError, match="not registered: artifact"):
        registry.get(StepType.ARTIFACT)


def test_build_default_step_runner_registry_registers_core_and_optional_runners() -> None:
    functions = FunctionStepRegistry()
    tool_registry = ToolRegistry()
    child_workflow = WorkflowSpec(
        workflow_id="child",
        name="Child",
        version="1.0",
        start_step_id="noop",
        steps=[
            StepSpec(
                step_id="noop",
                implementation="child.noop",
                read_keys=[],
                write_keys=[],
            )
        ],
    )

    registry = build_default_step_runner_registry(
        functions,
        tool_registry=tool_registry,
        agent_runner=object(),
        agent_registry={"analyst": object()},
        workflow_registry={"child": child_workflow},
    )

    assert set(registry.registered_step_types()) == {
        StepType.AGENT_LOOP,
        StepType.ARTIFACT,
        StepType.FUNCTION,
        StepType.HUMAN_REVIEW,
        StepType.JOIN,
        StepType.MEMORY_CONSOLIDATE,
        StepType.MEMORY_INDEX,
        StepType.MEMORY_RECALL,
        StepType.MEMORY_WRITE,
        StepType.NOTIFICATION,
        StepType.PARALLEL_GROUP,
        StepType.PERSIST,
        StepType.QUALITY_GATE,
        StepType.ROUTER,
        StepType.SUBWORKFLOW,
        StepType.TOOL_BATCH,
        StepType.TOOL_CALL,
    }


def test_build_default_step_runner_registry_registers_dependency_bound_runners_without_dependencies() -> None:
    registry = build_default_step_runner_registry(FunctionStepRegistry())

    assert registry.is_registered(StepType.FUNCTION)
    assert registry.is_registered(StepType.PARALLEL_GROUP)
    assert registry.is_registered(StepType.ARTIFACT)
    assert registry.is_registered(StepType.ROUTER)
    assert registry.is_registered(StepType.TOOL_CALL)
    assert registry.is_registered(StepType.MEMORY_CONSOLIDATE)
    assert registry.is_registered(StepType.MEMORY_RECALL)
    assert registry.is_registered(StepType.MEMORY_WRITE)
    assert registry.is_registered(StepType.AGENT_LOOP)
    assert registry.is_registered(StepType.SUBWORKFLOW)

    descriptors = {item.runner_id: item for item in registry.describe()}
    assert descriptors["builtin.tool"].missing_dependencies == ["tool_registry"]
    assert descriptors["builtin.memory_consolidate"].missing_dependencies == ["memory_runtime"]
    assert descriptors["builtin.memory_recall"].missing_dependencies == ["memory_runtime"]
    assert descriptors["builtin.memory_write"].missing_dependencies == ["memory_runtime"]
    assert descriptors["builtin.agent_loop"].missing_dependencies == [
        "agent_registry",
        "llm_client",
    ]
    assert descriptors["builtin.artifact"].missing_dependencies == ["artifact_publisher"]
    assert descriptors["builtin.human_review"].missing_dependencies == ["human_review_store"]
    assert descriptors["builtin.subworkflow"].missing_dependencies == ["workflow_executor"]


class _CustomRunner:
    def run(self, step: StepSpec, buffer) -> StepOutcome:
        buffer.write("artifact_marker", step.implementation)
        return StepOutcome(
            status=StepStatus.SUCCEEDED,
            outputs={"artifact_marker": step.implementation},
        )
