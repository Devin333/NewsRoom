from __future__ import annotations

from enum import Enum
import re
import time
from typing import Any, Protocol

from pydantic import BaseModel, Field

from framework.specs import StepSpec, StepStatus, StepType
from framework.workflow.buffer.data_buffer import StepScopedDataBufferView
from framework.workflow.runtime.result import StepOutcome
from framework.workflow.runners.base import (
    StepExecutionError,
    StepRunnerCapability,
    StepRunnerSideEffectLevel,
    ValidationErrorItem,
)

try:  # pragma: no cover - exercised when PRD-2 is present.
    from framework.skills.context import SkillRunContext as SkillRunContext
except ModuleNotFoundError:  # pragma: no cover - fallback is covered through behavior.

    class SkillRunContext(BaseModel):
        run_id: str = Field(min_length=1)
        skill_name: str = Field(min_length=1)
        caller_type: str = "unknown"
        caller_id: str | None = None
        trace_id: str | None = None
        memory_scope: str | None = None
        dry_run: bool = False
        timeout_seconds: int | None = None
        max_retries: int = 0
        metadata: dict[str, Any] = Field(default_factory=dict)

        @classmethod
        def for_workflow(
            cls,
            skill_name: str,
            workflow_run_id: str,
            step_id: str,
        ) -> "SkillRunContext":
            return cls(
                run_id=workflow_run_id,
                skill_name=skill_name,
                caller_type="workflow",
                caller_id=workflow_run_id,
                metadata={
                    "workflow_run_id": workflow_run_id,
                    "step_id": step_id,
                },
            )


class SkillRunnerProtocol(Protocol):
    def run(
        self,
        skill_name: str,
        input_data: dict[str, Any],
        context: SkillRunContext | None = None,
    ) -> Any:
        ...


_TEMPLATE_REF_PATTERN = re.compile(r"^\s*\{\{\s*(?P<key>[^{}]+?)\s*\}\}\s*$")


def resolve_skill_input(value: Any, buffer: Any) -> Any:
    if isinstance(value, str):
        match = _TEMPLATE_REF_PATTERN.match(value)
        if match is not None:
            return _buffer_read(buffer, match.group("key").strip())
        return value
    if isinstance(value, dict):
        return {str(key): resolve_skill_input(item, buffer) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_skill_input(item, buffer) for item in value]
    return value


class SkillStepRunner:
    capability = StepRunnerCapability(
        step_type=StepType.SKILL,
        runner_id="skill-step-runner",
        version="1.0.0",
        supports_checkpoint=True,
        supports_resume=True,
        supports_timeout=True,
        supports_retry=True,
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
        return {
            "step_type": "skill",
            "runner_id": "skill-step-runner",
            "version": "1.0.0",
            "supports_checkpoint": True,
            "supports_resume": True,
            "supports_timeout": True,
            "supports_retry": True,
            "side_effect_level": "medium",
            "required_dependencies": ["SkillRunner"],
        }

    def configure_run_context(self, *, artifact_manager: Any, run_id: str) -> None:
        _ = artifact_manager
        self._run_id = run_id

    def configure_trace_context(self, *, trace_context: Any) -> None:
        self._trace_context = trace_context

    def can_resolve(self, step: Any) -> bool:
        return _step_type_value(step) == "skill"

    def validate_step(self, step: Any) -> list[ValidationErrorItem]:
        issues: list[ValidationErrorItem] = []
        step_id = _step_id(step)
        if not step_id:
            issues.append(
                ValidationErrorItem(
                    code="skill_step_missing_id",
                    message="Skill step requires id.",
                    field="id",
                )
            )
        if _step_type_value(step) != "skill":
            issues.append(
                ValidationErrorItem(
                    code="skill_step_invalid_type",
                    message="SkillStepRunner only supports type='skill'.",
                    field="type",
                )
            )
        skill_name = _skill_name(step)
        if not skill_name:
            issues.append(
                ValidationErrorItem(
                    code="skill_step_missing_skill",
                    message="Skill step requires skill.",
                    field="skill",
                )
            )
        input_spec = _skill_input_spec(step)
        if not isinstance(input_spec, dict):
            issues.append(
                ValidationErrorItem(
                    code="skill_step_invalid_input",
                    message="Skill step input must be a dict.",
                    field="input",
                )
            )
        output_key = _raw_output_key(step)
        if output_key is not None and not isinstance(output_key, str):
            issues.append(
                ValidationErrorItem(
                    code="skill_step_invalid_output_key",
                    message="Skill step output_key must be a string when set.",
                    field="output_key",
                )
            )
        timeout_seconds = _timeout_seconds(step)
        if timeout_seconds is not None and (
            type(timeout_seconds) is not int or timeout_seconds <= 0
        ):
            issues.append(
                ValidationErrorItem(
                    code="skill_step_invalid_timeout",
                    message="Skill step timeout_seconds must be a positive integer when set.",
                    field="timeout_seconds",
                )
            )
        fail_workflow_on_error = _fail_workflow_on_error(step)
        if not isinstance(fail_workflow_on_error, bool):
            issues.append(
                ValidationErrorItem(
                    code="skill_step_invalid_fail_workflow_on_error",
                    message="Skill step fail_workflow_on_error must be a bool.",
                    field="fail_workflow_on_error",
                )
            )
        return issues

    def run(self, step: Any, buffer: StepScopedDataBufferView | dict[str, Any]) -> StepOutcome:
        started = time.perf_counter()
        try:
            issues = self.validate_step(step)
            if issues:
                raise StepExecutionError("; ".join(item.message for item in issues))

            step_id = _step_id(step)
            skill_name = _skill_name(step)
            input_spec = _skill_input_spec(step)
            resolver = self.input_resolver or resolve_skill_input
            input_data = resolver(input_spec, buffer)
            if not isinstance(input_data, dict):
                raise StepExecutionError("Skill step resolved input must be a dict.")

            context = self._build_context(step, buffer)
            skill_result = self.skill_runner.run(skill_name, input_data, context=context)
            outputs = self._write_outputs(step, buffer, skill_result)
            status = _skill_result_status(skill_result)
            metrics = _skill_step_metrics(step, started=started, outputs=outputs)
            warnings = _skill_warnings(skill_result)

            if status == "success":
                return StepOutcome(
                    status=StepStatus.SUCCEEDED,
                    outputs=outputs,
                    metrics=metrics,
                    warnings=warnings,
                    metadata=_outcome_metadata(skill_name, status),
                )
            if status == "partial":
                return StepOutcome(
                    status=StepStatus.SUCCEEDED,
                    outputs=outputs,
                    metrics=metrics,
                    warnings=[
                        *warnings,
                        f"Skill step '{step_id}' completed with partial result.",
                    ],
                    next_hint="skill_partial",
                    metadata=_outcome_metadata(skill_name, status),
                )
            if status == "skipped":
                return StepOutcome(
                    status=StepStatus.SKIPPED,
                    outputs=outputs,
                    metrics=metrics,
                    warnings=warnings,
                    next_hint="skill_skipped",
                    metadata=_outcome_metadata(skill_name, status),
                )

            message = _skill_failure_message(
                step_id=step_id,
                skill_name=skill_name,
                skill_result=skill_result,
            )
            if not _fail_workflow_on_error(step):
                return StepOutcome(
                    status=StepStatus.SUCCEEDED,
                    outputs=outputs,
                    metrics=metrics,
                    warnings=[*warnings, message],
                    next_hint="skill_failed_warning",
                    metadata=_outcome_metadata(skill_name, status),
                )
            return StepOutcome(
                status=StepStatus.FAILED,
                outputs=outputs,
                error_type="SkillStepFailed",
                error_message=message,
                error_details={
                    "skill_name": skill_name,
                    "skill_status": status,
                    "errors": _skill_errors_payload(skill_result),
                },
                metrics=metrics,
                warnings=warnings,
                metadata=_outcome_metadata(skill_name, status),
            )
        except Exception as exc:
            return StepOutcome(
                status=StepStatus.FAILED,
                error_type=type(exc).__name__,
                error_message=str(exc),
                metrics=_skill_step_metrics(step, started=started, outputs={}),
            )

    def _build_context(self, step: Any, buffer: Any) -> SkillRunContext:
        step_id = _step_id(step)
        skill_name = _skill_name(step)
        workflow_run_id = _workflow_run_id(buffer, self._run_id)
        context = SkillRunContext.for_workflow(
            skill_name=skill_name,
            workflow_run_id=workflow_run_id,
            step_id=step_id,
        )
        trace_id = _trace_id(buffer, self._trace_context)
        if trace_id is not None:
            context.trace_id = trace_id
        timeout_seconds = _timeout_seconds(step)
        if timeout_seconds is not None:
            context.timeout_seconds = timeout_seconds
        retry = _retry(step)
        if isinstance(retry, dict):
            max_retries = retry.get("max_retries") or retry.get("max_attempts")
            if max_retries is not None:
                context.max_retries = int(max_retries)
        context.metadata.update(
            {
                "workflow_step_id": step_id,
                "workflow_step_type": "skill",
            }
        )
        return context

    def _write_outputs(self, step: Any, buffer: Any, skill_result: Any) -> dict[str, Any]:
        step_id = _step_id(step)
        output = _skill_output(skill_result)
        outputs: dict[str, Any] = {}

        if _store_full_result(step):
            key = _result_key(step)
            _buffer_write(
                buffer,
                key,
                skill_result,
                lineage={"step_id": step_id, "runner_id": self.capability.runner_id},
            )
            outputs[key] = skill_result
        if _store_output(step):
            key = _output_buffer_key(step)
            _buffer_write(
                buffer,
                key,
                output,
                lineage={"step_id": step_id, "runner_id": self.capability.runner_id},
            )
            outputs[key] = output
        output_key = _output_key(step)
        if output_key:
            _buffer_write(
                buffer,
                output_key,
                output,
                lineage={"step_id": step_id, "runner_id": self.capability.runner_id},
            )
            outputs[output_key] = output
        return outputs


def _step_type_value(step: Any) -> str | None:
    value = getattr(step, "step_type", None)
    if value is None:
        value = getattr(step, "type", None)
    if callable(value):
        value = value()
    if isinstance(value, Enum):
        return str(value.value)
    if value is None:
        return None
    return str(value)


def _step_id(step: Any) -> str:
    value = getattr(step, "step_id", None)
    if value is None:
        value = getattr(step, "id", None)
    return str(value or "")


def _metadata(step: Any) -> dict[str, Any]:
    return dict(getattr(step, "metadata", None) or {})


def _skill_name(step: Any) -> str:
    value = getattr(step, "skill", None)
    if value is None:
        value = _metadata(step).get("skill")
    if value is None and isinstance(step, StepSpec):
        value = step.implementation
    return str(value or "").strip()


def _skill_input_spec(step: Any) -> Any:
    if hasattr(step, "input"):
        return getattr(step, "input")
    return _metadata(step).get("input", {})


def _output_key(step: Any) -> str | None:
    value = _raw_output_key(step)
    if value is None:
        return None
    return str(value)


def _raw_output_key(step: Any) -> Any:
    value = getattr(step, "output_key", None)
    if value is None:
        value = _metadata(step).get("output_key")
    return value


def _timeout_seconds(step: Any) -> int | None:
    value = getattr(step, "timeout_seconds", None)
    if value is None:
        value = _metadata(step).get("timeout_seconds")
    if value is None and isinstance(step, StepSpec):
        value = step.timeout_policy.timeout_seconds
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value  # type: ignore[return-value]


def _retry(step: Any) -> Any:
    value = getattr(step, "retry", None)
    if value is not None:
        return value
    return _metadata(step).get("retry")


def _store_full_result(step: Any) -> bool:
    value = getattr(step, "store_full_result", None)
    if value is None:
        value = _metadata(step).get("store_full_result", True)
    return bool(value)


def _store_output(step: Any) -> bool:
    value = getattr(step, "store_output", None)
    if value is None:
        value = _metadata(step).get("store_output", True)
    return bool(value)


def _fail_workflow_on_error(step: Any) -> bool:
    value = getattr(step, "fail_workflow_on_error", None)
    if value is None:
        value = _metadata(step).get("fail_workflow_on_error", True)
    return value


def _result_key(step: Any) -> str:
    method = getattr(step, "result_key", None)
    if callable(method):
        return str(method())
    return f"{_step_id(step)}.result"


def _output_buffer_key(step: Any) -> str:
    method = getattr(step, "output_buffer_key", None)
    if callable(method):
        return str(method())
    return f"{_step_id(step)}.output"


def _buffer_read(buffer: Any, key: str) -> Any:
    read = getattr(buffer, "read", None)
    if callable(read):
        return read(key)
    return buffer[key]


def _buffer_write(
    buffer: Any,
    key: str,
    value: Any,
    *,
    lineage: dict[str, Any] | None = None,
) -> None:
    write = getattr(buffer, "write", None)
    if callable(write):
        write(key, value, lineage=lineage)
        return
    buffer[key] = value


def _workflow_run_id(buffer: Any, configured_run_id: str | None) -> str:
    for source in (buffer, getattr(buffer, "buffer", None)):
        value = getattr(source, "run_id", None)
        if value:
            return str(value)
    return configured_run_id or "workflow-run"


def _trace_id(buffer: Any, trace_context: Any) -> str | None:
    for source in (buffer, getattr(buffer, "buffer", None), trace_context):
        value = getattr(source, "trace_id", None)
        if value:
            return str(value)
    return None


def _skill_result_status(skill_result: Any) -> str:
    status = getattr(skill_result, "status", None)
    if isinstance(status, Enum):
        return str(status.value)
    return str(status or "failed")


def _skill_output(skill_result: Any) -> Any:
    return getattr(skill_result, "output", {})


def _skill_errors_payload(skill_result: Any) -> list[Any]:
    return list(getattr(skill_result, "errors", []) or [])


def _skill_warnings(skill_result: Any) -> list[str]:
    warnings: list[str] = []
    for warning in list(getattr(skill_result, "warnings", []) or []):
        message = _field_value(warning, "message")
        warnings.append(str(message if message is not None else warning))
    return warnings


def _skill_failure_message(*, step_id: str, skill_name: str, skill_result: Any) -> str:
    first_error = _first_error_message(skill_result)
    if not first_error:
        first_error = "skill returned failed status"
    return f"Skill step '{step_id}' failed running skill '{skill_name}': {first_error}"


def _first_error_message(skill_result: Any) -> str:
    errors = _skill_errors_payload(skill_result)
    if not errors:
        return ""
    first = errors[0]
    message = _field_value(first, "message")
    if message is None:
        return str(first)
    return str(message)


def _field_value(value: Any, field_name: str) -> Any:
    if isinstance(value, dict):
        return value.get(field_name)
    return getattr(value, field_name, None)


def _skill_step_metrics(
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


def _outcome_metadata(skill_name: str, status: str) -> dict[str, Any]:
    return {
        "skill_name": skill_name,
        "skill_status": status,
    }


__all__ = [
    "SkillRunContext",
    "SkillRunnerProtocol",
    "SkillStepRunner",
    "resolve_skill_input",
]
