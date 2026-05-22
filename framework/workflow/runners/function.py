"""Function step runner."""

from __future__ import annotations

from collections.abc import Callable
import time
from typing import Any

from framework.specs import StepSpec, StepStatus, StepType
from framework.workflow.buffer import StepScopedDataBufferView
from framework.workflow.runtime.result import StepOutcome
from framework.workflow.runners._utils import (
    contract_metrics,
    failed_outcome,
    validated_outputs,
)
from framework.workflow.runners.base import (
    StepExecutionError,
    StepRunnerCapability,
    StepRunnerSideEffectLevel,
    ValidationErrorItem,
)

FunctionStep = Callable[[StepScopedDataBufferView], dict[str, Any] | None]


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
            raise StepExecutionError(
                f"function step is not registered: {implementation}"
            ) from exc

    def is_registered(self, implementation: str) -> bool:
        return implementation in self._functions


class FunctionStepRunner:
    capability = StepRunnerCapability(
        step_type=StepType.FUNCTION,
        runner_id="builtin.function",
        version="1.0.0",
        supports_checkpoint=True,
        supports_resume=True,
        supports_timeout=True,
        supports_retry=True,
        side_effect_level=StepRunnerSideEffectLevel.NONE,
        required_dependencies=["function_registry"],
        description="Runs an in-process Python function step.",
    )

    def __init__(self, registry: FunctionStepRegistry) -> None:
        self._registry = registry

    def can_resolve(self, step: StepSpec) -> bool:
        return step.step_type == StepType.FUNCTION and self._registry.is_registered(
            step.implementation
        )

    def validate_step(self, step: StepSpec) -> list[ValidationErrorItem]:
        if step.implementation:
            return []
        return [
            ValidationErrorItem(
                code="function_missing_implementation",
                message="Function step requires implementation.",
                field="implementation",
            )
        ]

    def run(self, step: StepSpec, buffer: StepScopedDataBufferView) -> StepOutcome:
        started = time.perf_counter()
        try:
            if step.step_type != StepType.FUNCTION:
                raise StepExecutionError(
                    f"unsupported step type for FunctionStepRunner: {step.step_type}"
                )

            function = self._registry.get(step.implementation)
            raw_outputs = function(buffer)
            outputs = validated_outputs(
                step,
                raw_outputs,
                runner_name="function step",
            )
            for key, value in outputs.items():
                buffer.write(key, value)

            return StepOutcome(
                status=StepStatus.SUCCEEDED,
                outputs=outputs,
                metrics=contract_metrics(
                    step,
                    started=started,
                    outputs=outputs,
                ),
            )
        except Exception as exc:
            return failed_outcome(
                step,
                exc,
                started=started,
                runner_name="FunctionStepRunner",
            )

__all__ = ["FunctionStep", "FunctionStepRegistry", "FunctionStepRunner"]


