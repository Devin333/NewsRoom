from __future__ import annotations

from core.framework.specs import StepSpec, StepType, WorkflowSpec
from core.framework.workflow import (
    FunctionStepRegistry,
    FunctionStepRunner,
    StepOutcome,
    StepRunnerRegistry,
    WorkflowCompileIssueCode,
    WorkflowCompiler,
)


def test_compile_passes_when_step_type_runner_is_registered() -> None:
    registry = StepRunnerRegistry()
    registry.register(StepType.ARTIFACT, _AnyRunner())

    result = WorkflowCompiler(runner_registry=registry).compile(
        _spec(StepSpec("finish", "artifact.write", step_type=StepType.ARTIFACT))
    )

    assert result.passed is True
    assert result.required_step_types == [StepType.ARTIFACT]
    assert result.required_implementations == ["artifact.write"]


def test_compile_fails_when_step_type_runner_is_missing() -> None:
    result = WorkflowCompiler(runner_registry=StepRunnerRegistry()).compile(
        _spec(StepSpec("finish", "artifact.write", step_type=StepType.ARTIFACT))
    )

    assert result.passed is False
    assert result.has_error(WorkflowCompileIssueCode.RUNNER_NOT_FOUND)


def test_compile_passes_when_function_implementation_exists() -> None:
    functions = FunctionStepRegistry()
    functions.register("sample.finish", lambda buffer: {"report": "ok"})
    registry = StepRunnerRegistry.with_function_runner(FunctionStepRunner(functions))

    result = WorkflowCompiler(runner_registry=registry).compile(
        _spec(StepSpec("finish", "sample.finish", write_keys=["report"]))
    )

    assert result.passed is True


def test_compile_fails_when_function_implementation_is_missing() -> None:
    registry = StepRunnerRegistry.with_function_runner(FunctionStepRunner(FunctionStepRegistry()))

    result = WorkflowCompiler(runner_registry=registry).compile(
        _spec(StepSpec("finish", "sample.finish", write_keys=["report"]))
    )

    assert result.passed is False
    assert result.has_error(WorkflowCompileIssueCode.RUNNER_IMPLEMENTATION_NOT_FOUND)


class _AnyRunner:
    def run(self, step, buffer) -> StepOutcome:  # pragma: no cover - not executed by compiler
        raise AssertionError("compiler should not execute step runners")


def _spec(step: StepSpec) -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="compiler-runner",
        name="Compiler Runner",
        version="1.0",
        start_step_id=step.step_id,
        terminal_step_ids=[step.step_id],
        steps=[step],
    )
