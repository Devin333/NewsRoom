from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from core.framework.specs import StepSpec, StepStatus, StepType
from core.framework.workflow.buffer import ScopedDataBuffer
from core.framework.workflow.result import StepOutcome

FunctionStep = Callable[[ScopedDataBuffer], dict[str, Any] | None]


class StepExecutionError(RuntimeError):
    """Raised when a step cannot be executed by a runner."""


class StepRunner(Protocol):
    def run(self, step: StepSpec, buffer: ScopedDataBuffer) -> StepOutcome:
        ...


class StepRunnerRegistry:
    def __init__(self) -> None:
        self._runners: dict[StepType, StepRunner] = {}

    @classmethod
    def with_function_runner(cls, runner: FunctionStepRunner) -> StepRunnerRegistry:
        registry = cls()
        registry.register(StepType.FUNCTION, runner)
        return registry

    def register(self, step_type: StepType | str, runner: StepRunner) -> None:
        actual_step_type = StepType(step_type)
        if actual_step_type in self._runners:
            raise StepExecutionError(f"step runner is already registered: {actual_step_type.value}")
        self._runners[actual_step_type] = runner

    def get(self, step_type: StepType | str) -> StepRunner:
        actual_step_type = StepType(step_type)
        try:
            return self._runners[actual_step_type]
        except KeyError as exc:
            raise StepExecutionError(f"step runner is not registered: {actual_step_type.value}") from exc

    def is_registered(self, step_type: StepType | str) -> bool:
        return StepType(step_type) in self._runners

    def missing_step_types(self, step_types: list[StepType | str]) -> list[StepType]:
        missing = {
            StepType(step_type)
            for step_type in step_types
            if not self.is_registered(step_type)
        }
        return sorted(missing, key=lambda step_type: step_type.value)

    def registered_step_types(self) -> list[StepType]:
        return sorted(self._runners, key=lambda step_type: step_type.value)


class FunctionStepRegistry:
    def __init__(self) -> None:
        self._functions: dict[str, FunctionStep] = {}

    def register(self, implementation: str, function: FunctionStep) -> None:
        if not implementation:
            raise ValueError("implementation is required")
        self._functions[implementation] = function

    def get(self, implementation: str) -> FunctionStep:
        try:
            return self._functions[implementation]
        except KeyError as exc:
            raise StepExecutionError(f"function step is not registered: {implementation}") from exc


class FunctionStepRunner:
    def __init__(self, registry: FunctionStepRegistry) -> None:
        self._registry = registry

    def run(self, step: StepSpec, buffer: ScopedDataBuffer) -> StepOutcome:
        if step.step_type != StepType.FUNCTION:
            raise StepExecutionError(f"unsupported step type for FunctionStepRunner: {step.step_type}")

        function = self._registry.get(step.implementation)
        raw_outputs = function(buffer)
        outputs = raw_outputs or {}
        if not isinstance(outputs, dict):
            raise StepExecutionError(
                f"function step {step.step_id} returned {type(outputs).__name__}, expected dict"
            )

        missing = [key for key in step.required_output_keys if key not in outputs]
        if missing:
            raise StepExecutionError(
                f"function step {step.step_id} did not return required output keys: "
                f"{', '.join(sorted(missing))}"
            )

        for key, value in outputs.items():
            buffer.write(key, value)

        return StepOutcome(status=StepStatus.SUCCEEDED, outputs=outputs)
