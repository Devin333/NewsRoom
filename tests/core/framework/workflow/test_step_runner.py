import pytest

from core.framework.specs import StepSpec
from core.framework.workflow import (
    DataBuffer,
    FunctionStepRegistry,
    FunctionStepRunner,
    StepExecutionError,
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
