from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.framework.specs import StepSpec, StepStatus, StepType
from core.framework.workflow.buffer import ScopedDataBuffer
from core.framework.workflow.result import StepOutcome

FunctionStep = Callable[[ScopedDataBuffer], dict[str, Any] | None]


class StepExecutionError(RuntimeError):
    """Raised when a step cannot be executed by a runner."""


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
