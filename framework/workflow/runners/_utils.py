from __future__ import annotations

import json
import time
from typing import Any

from framework.specs import StepSpec, StepStatus
from framework.workflow.runtime.result import StepOutcome
from framework.workflow.runners.base import StepExecutionError


def validated_outputs(
    step: StepSpec,
    raw_outputs: dict[str, Any] | None,
    *,
    runner_name: str,
    allow_extra: bool = False,
    allow_missing_required: bool = False,
) -> dict[str, Any]:
    outputs = raw_outputs or {}
    if not isinstance(outputs, dict):
        raise StepExecutionError(
            f"{runner_name} {step.step_id} returned {type(outputs).__name__}, expected dict"
        )
    extra_keys = sorted(set(outputs) - set(step.write_keys))
    if extra_keys and not allow_extra:
        raise StepExecutionError(
            f"{runner_name} {step.step_id} returned undeclared output keys: "
            f"{', '.join(extra_keys)}"
        )
    missing = sorted(set(step.required_output_keys) - set(outputs))
    if missing and not allow_missing_required:
        raise StepExecutionError(
            f"{runner_name} {step.step_id} did not return required output keys: "
            f"{', '.join(missing)}"
        )
    return {
        str(key): value
        for key, value in outputs.items()
        if str(key) in set(step.write_keys)
    }


def contract_metrics(
    step: StepSpec,
    *,
    started: float,
    outputs: dict[str, Any] | None = None,
    artifact_count: int = 0,
) -> dict[str, Any]:
    actual_outputs = outputs or {}
    return {
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        "attempt": 1,
        "input_key_count": len(step.read_keys),
        "output_key_count": len(actual_outputs),
        "artifact_count": artifact_count,
    }


def with_contract_metrics(
    metrics: dict[str, Any],
    step: StepSpec,
    *,
    started: float,
    outputs: dict[str, Any] | None = None,
    artifact_count: int = 0,
) -> dict[str, Any]:
    return {
        **metrics,
        **contract_metrics(
            step,
            started=started,
            outputs=outputs,
            artifact_count=artifact_count,
        ),
    }


def failed_outcome(
    step: StepSpec,
    exc: Exception,
    *,
    started: float,
    runner_name: str,
) -> StepOutcome:
    return StepOutcome(
        status=StepStatus.FAILED,
        error_type=type(exc).__name__,
        error_message=str(exc),
        error_details={"runner": runner_name},
        metrics=contract_metrics(step, started=started),
    )


def metadata_float(step: StepSpec, key: str, default: float | None) -> float | None:
    value = step.metadata.get(key, default)
    if value is None:
        return None
    return float(value)


def buffer_value(buffer: Any, key: Any, default: Any) -> Any:
    if key is None:
        return default
    key = str(key)
    if key not in buffer.list_allowed_reads() or not buffer.exists(key):
        return default
    return buffer.read(key)


def buffer_metric(
    buffer: Any,
    step: StepSpec,
    metadata_key: str,
    default_key: str,
) -> float | None:
    value = buffer_value(buffer, step.metadata.get(f"{metadata_key}_key"), None)
    if value is None:
        value = buffer_value(buffer, default_key, None)
    if value is None:
        return None
    return float(value)


def json_artifact_bytes(content: Any) -> bytes:
    from framework.shared.json import to_jsonable as to_json_safe

    return (
        json.dumps(
            to_json_safe(content),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
