from __future__ import annotations

from typing import Any

from framework.workflow.runners.base import ValidationErrorItem
from framework.workflow.runners.skill.accessors import (
    fail_workflow_on_error,
    raw_output_key,
    skill_input_spec,
    skill_name,
    step_id,
    step_type_value,
    timeout_seconds,
)


def validate_skill_step(step: Any) -> list[ValidationErrorItem]:
    issues: list[ValidationErrorItem] = []
    if not step_id(step):
        issues.append(
            ValidationErrorItem(
                code="skill_step_missing_id",
                message="Skill step requires id.",
                field="id",
            )
        )
    if step_type_value(step) != "skill":
        issues.append(
            ValidationErrorItem(
                code="skill_step_invalid_type",
                message="SkillStepRunner only supports type='skill'.",
                field="type",
            )
        )
    if not skill_name(step):
        issues.append(
            ValidationErrorItem(
                code="skill_step_missing_skill",
                message="Skill step requires skill.",
                field="skill",
            )
        )
    input_spec = skill_input_spec(step)
    if not isinstance(input_spec, dict):
        issues.append(
            ValidationErrorItem(
                code="skill_step_invalid_input",
                message="Skill step input must be a dict.",
                field="input",
            )
        )
    output_key = raw_output_key(step)
    if output_key is not None and not isinstance(output_key, str):
        issues.append(
            ValidationErrorItem(
                code="skill_step_invalid_output_key",
                message="Skill step output_key must be a string when set.",
                field="output_key",
            )
        )
    resolved_timeout_seconds = timeout_seconds(step)
    if resolved_timeout_seconds is not None and (
        type(resolved_timeout_seconds) is not int or resolved_timeout_seconds <= 0
    ):
        issues.append(
            ValidationErrorItem(
                code="skill_step_invalid_timeout",
                message="Skill step timeout_seconds must be a positive integer when set.",
                field="timeout_seconds",
            )
        )
    resolved_fail_workflow_on_error = fail_workflow_on_error(step)
    if not isinstance(resolved_fail_workflow_on_error, bool):
        issues.append(
            ValidationErrorItem(
                code="skill_step_invalid_fail_workflow_on_error",
                message="Skill step fail_workflow_on_error must be a bool.",
                field="fail_workflow_on_error",
            )
        )
    return issues


__all__ = [
    "validate_skill_step",
]
