"""Router step runner."""

from __future__ import annotations

import time

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
    default_runner_can_resolve,
)


class RouterStepRunner:
    capability = StepRunnerCapability(
        step_type=StepType.ROUTER,
        runner_id="builtin.router",
        version="1.0.0",
        supports_checkpoint=False,
        supports_resume=True,
        supports_timeout=False,
        supports_retry=True,
        side_effect_level=StepRunnerSideEffectLevel.NONE,
        required_dependencies=[],
        description="Selects a deterministic route hint.",
    )

    def can_resolve(self, step: StepSpec) -> bool:
        return default_runner_can_resolve(self.capability, step)

    def validate_step(self, step: StepSpec) -> list[ValidationErrorItem]:
        return []

    def run(self, step: StepSpec, buffer: StepScopedDataBufferView) -> StepOutcome:
        started = time.perf_counter()
        try:
            if step.step_type != StepType.ROUTER:
                raise StepExecutionError(
                    f"unsupported step type for RouterStepRunner: {step.step_type}"
                )

            route = step.metadata.get("route")
            if route is None:
                route_key = str(step.metadata.get("route_key") or "route")
                route = buffer.read(route_key)
            route = str(route)
            output_key = str(step.metadata.get("output_key") or "route")
            outputs = validated_outputs(
                step, {output_key: route}, runner_name="router step"
            )
            if output_key in buffer.list_allowed_writes():
                buffer.write(output_key, route)
            return StepOutcome(
                status=StepStatus.SUCCEEDED,
                outputs=outputs,
                metrics=contract_metrics(step, started=started, outputs=outputs),
                next_hint=route,
            )
        except Exception as exc:
            return failed_outcome(
                step,
                exc,
                started=started,
                runner_name="RouterStepRunner",
            )

__all__ = ["RouterStepRunner"]


