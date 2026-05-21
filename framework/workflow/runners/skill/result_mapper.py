from __future__ import annotations

from enum import Enum
import time
from typing import Any

from framework.specs import StepStatus
from framework.workflow.runtime.result import StepOutcome
from framework.workflow.runners.skill.accessors import fail_workflow_on_error, step_id


def skill_result_status(skill_result: Any) -> str:
    status = getattr(skill_result, "status", None)
    if isinstance(status, Enum):
        return str(status.value)
    return str(status or "failed")


def skill_output(skill_result: Any) -> Any:
    return getattr(skill_result, "output", {})


def skill_errors_payload(skill_result: Any) -> list[Any]:
    return list(getattr(skill_result, "errors", []) or [])


def skill_warnings(skill_result: Any) -> list[str]:
    warnings: list[str] = []
    for warning in list(getattr(skill_result, "warnings", []) or []):
        message = field_value(warning, "message")
        warnings.append(str(message if message is not None else warning))
    return warnings


def map_skill_result_to_outcome(
    step: Any,
    skill_name: str,
    skill_result: Any,
    *,
    started: float,
    outputs: dict[str, Any],
) -> StepOutcome:
    resolved_step_id = step_id(step)
    status = skill_result_status(skill_result)
    metrics = skill_step_metrics(step, started=started, outputs=outputs)
    warnings = skill_warnings(skill_result)

    if status == "success":
        return StepOutcome(
            status=StepStatus.SUCCEEDED,
            outputs=outputs,
            metrics=metrics,
            warnings=warnings,
            metadata=outcome_metadata(skill_name, status),
        )
    if status == "partial":
        return StepOutcome(
            status=StepStatus.SUCCEEDED,
            outputs=outputs,
            metrics=metrics,
            warnings=[
                *warnings,
                f"Skill step '{resolved_step_id}' completed with partial result.",
            ],
            next_hint="skill_partial",
            metadata=outcome_metadata(skill_name, status),
        )
    if status == "skipped":
        return StepOutcome(
            status=StepStatus.SKIPPED,
            outputs=outputs,
            metrics=metrics,
            warnings=warnings,
            next_hint="skill_skipped",
            metadata=outcome_metadata(skill_name, status),
        )

    message = skill_failure_message(
        step_id=resolved_step_id,
        skill_name=skill_name,
        skill_result=skill_result,
    )
    if not fail_workflow_on_error(step):
        return StepOutcome(
            status=StepStatus.SUCCEEDED,
            outputs=outputs,
            metrics=metrics,
            warnings=[*warnings, message],
            next_hint="skill_failed_warning",
            metadata=outcome_metadata(skill_name, status),
        )
    return StepOutcome(
        status=StepStatus.FAILED,
        outputs=outputs,
        error_type="SkillStepFailed",
        error_message=message,
        error_details={
            "skill_name": skill_name,
            "skill_status": status,
            "errors": skill_errors_payload(skill_result),
        },
        metrics=metrics,
        warnings=warnings,
        metadata=outcome_metadata(skill_name, status),
    )


def skill_failure_message(*, step_id: str, skill_name: str, skill_result: Any) -> str:
    first_error = first_error_message(skill_result)
    if not first_error:
        first_error = "skill returned failed status"
    return f"Skill step '{step_id}' failed running skill '{skill_name}': {first_error}"


def first_error_message(skill_result: Any) -> str:
    errors = skill_errors_payload(skill_result)
    if not errors:
        return ""
    first = errors[0]
    message = field_value(first, "message")
    if message is None:
        return str(first)
    return str(message)


def field_value(value: Any, field_name: str) -> Any:
    if isinstance(value, dict):
        return value.get(field_name)
    return getattr(value, field_name, None)


def skill_step_metrics(
    step: Any,
    *,
    started: float,
    outputs: dict[str, Any],
) -> dict[str, Any]:
    read_keys = getattr(step, "read_keys", []) or []
    return {
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        "attempt": 1,
        "input_key_count": len(read_keys),
        "output_key_count": len(outputs),
        "artifact_count": 0,
    }


def outcome_metadata(skill_name: str, status: str) -> dict[str, Any]:
    return {
        "skill_name": skill_name,
        "skill_status": status,
    }


__all__ = [
    "map_skill_result_to_outcome",
    "skill_output",
    "skill_result_status",
    "skill_step_metrics",
]
