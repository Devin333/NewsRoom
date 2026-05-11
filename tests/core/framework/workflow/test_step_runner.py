import pytest

from core.framework.specs import StepSpec, StepStatus, StepType
from core.framework.workflow import (
    DataBuffer,
    FunctionStepRegistry,
    FunctionStepRunner,
    StepExecutionError,
    StepOutcome,
    StepRunnerRegistry,
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

    with pytest.raises(StepExecutionError, match="required output keys"):
        runner.run(
            StepSpec(
                step_id="empty",
                implementation="sample.empty",
                write_keys=["plan"],
                required_output_keys=["plan"],
            ),
            buffer.scope(read_keys=[], write_keys=["plan"]),
        )


def test_function_step_runner_rejects_unregistered_function() -> None:
    runner = FunctionStepRunner(FunctionStepRegistry())

    with pytest.raises(StepExecutionError, match="not registered"):
        runner.run(
            StepSpec(step_id="missing", implementation="sample.missing"),
            DataBuffer().scope(read_keys=[], write_keys=[]),
        )


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


class _CustomRunner:
    def run(self, step: StepSpec, buffer) -> StepOutcome:
        buffer.write("artifact_marker", step.implementation)
        return StepOutcome(
            status=StepStatus.SUCCEEDED,
            outputs={"artifact_marker": step.implementation},
        )
