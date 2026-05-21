from __future__ import annotations

import time
from typing import Any

from framework.specs import StepStatus, StepType
from framework.workflow.buffer.data_buffer import StepScopedDataBufferView
from framework.workflow.runtime.result import StepOutcome
from framework.workflow.runners.base import (
    StepExecutionError,
    StepRunnerCapability,
    StepRunnerSideEffectLevel,
    ValidationErrorItem,
)
from framework.workflow.runners.skill.accessors import (
    skill_input_spec,
    skill_name,
    step_type_value,
)
from framework.workflow.runners.skill.context import SkillRunnerProtocol
from framework.workflow.runners.skill.context_builder import build_skill_run_context
from framework.workflow.runners.skill.input_resolver import resolve_skill_input
from framework.workflow.runners.skill.output_writer import write_skill_outputs
from framework.workflow.runners.skill.result_mapper import (
    map_skill_result_to_outcome,
    skill_step_metrics,
)
from framework.workflow.runners.skill.validators import validate_skill_step


class SkillStepRunner:
    capability = StepRunnerCapability(
        step_type=StepType.SKILL,
        runner_id="skill-step-runner",
        version="1.0.0",
        supports_checkpoint=True,
        supports_resume=True,
        supports_timeout=False,
        supports_retry=False,
        side_effect_level=StepRunnerSideEffectLevel.EXTERNAL_WRITE,
        required_dependencies=["SkillRunner"],
        description="Runs a workflow skill step through an injected SkillRunner.",
    )

    def __init__(
        self,
        skill_runner: SkillRunnerProtocol,
        input_resolver: Any | None = None,
    ) -> None:
        self.skill_runner = skill_runner
        self.input_resolver = input_resolver
        self._run_id: str | None = None
        self._trace_context: Any | None = None

    def describe_capability(self) -> dict[str, Any]:
        return self.capability.to_dict()

    def configure_run_context(self, *, artifact_manager: Any, run_id: str) -> None:
        _ = artifact_manager
        self._run_id = run_id

    def configure_trace_context(self, *, trace_context: Any) -> None:
        self._trace_context = trace_context

    def can_resolve(self, step: Any) -> bool:
        return step_type_value(step) == "skill"

    def validate_step(self, step: Any) -> list[ValidationErrorItem]:
        return validate_skill_step(step)

    def run(self, step: Any, buffer: StepScopedDataBufferView | dict[str, Any]) -> StepOutcome:
        started = time.perf_counter()
        try:
            issues = self.validate_step(step)
            if issues:
                raise StepExecutionError("; ".join(item.message for item in issues))

            resolved_skill_name = skill_name(step)
            input_spec = skill_input_spec(step)
            resolver = self.input_resolver or resolve_skill_input
            input_data = resolver(input_spec, buffer)
            if not isinstance(input_data, dict):
                raise StepExecutionError("Skill step resolved input must be a dict.")

            context = build_skill_run_context(
                step,
                buffer,
                configured_run_id=self._run_id,
                trace_context=self._trace_context,
            )
            skill_result = self.skill_runner.run(resolved_skill_name, input_data, context=context)
            outputs = write_skill_outputs(
                step,
                buffer,
                skill_result,
                runner_id=self.capability.runner_id,
            )
            return map_skill_result_to_outcome(
                step,
                resolved_skill_name,
                skill_result,
                started=started,
                outputs=outputs,
            )
        except Exception as exc:
            return StepOutcome(
                status=StepStatus.FAILED,
                error_type=type(exc).__name__,
                error_message=str(exc),
                metrics=skill_step_metrics(step, started=started, outputs={}),
            )


__all__ = [
    "SkillStepRunner",
]
