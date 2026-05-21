from __future__ import annotations

from enum import Enum
from typing import Any

from framework.specs import StepSpec


def step_type_value(step: Any) -> str | None:
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


def step_id(step: Any) -> str:
    value = getattr(step, "step_id", None)
    if value is None:
        value = getattr(step, "id", None)
    return str(value or "")


def metadata(step: Any) -> dict[str, Any]:
    return dict(getattr(step, "metadata", None) or {})


def skill_name(step: Any) -> str:
    value = getattr(step, "skill", None)
    if value is None:
        value = metadata(step).get("skill")
    if value is None and isinstance(step, StepSpec):
        value = step.implementation
    return str(value or "").strip()


def skill_input_spec(step: Any) -> Any:
    if hasattr(step, "input"):
        return getattr(step, "input")
    return metadata(step).get("input", {})


def output_key(step: Any) -> str | None:
    value = raw_output_key(step)
    if value is None:
        return None
    return str(value)


def raw_output_key(step: Any) -> Any:
    value = getattr(step, "output_key", None)
    if value is None:
        value = metadata(step).get("output_key")
    return value


def timeout_seconds(step: Any) -> int | None:
    value = getattr(step, "timeout_seconds", None)
    if value is None:
        value = metadata(step).get("timeout_seconds")
    if value is None and isinstance(step, StepSpec):
        value = step.timeout_policy.timeout_seconds
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value  # type: ignore[return-value]


def retry(step: Any) -> Any:
    value = getattr(step, "retry", None)
    if value is not None:
        return value
    return metadata(step).get("retry")


def store_full_result(step: Any) -> bool:
    value = getattr(step, "store_full_result", None)
    if value is None:
        value = metadata(step).get("store_full_result", True)
    return bool(value)


def store_output(step: Any) -> bool:
    value = getattr(step, "store_output", None)
    if value is None:
        value = metadata(step).get("store_output", True)
    return bool(value)


def fail_workflow_on_error(step: Any) -> bool:
    value = getattr(step, "fail_workflow_on_error", None)
    if value is None:
        value = metadata(step).get("fail_workflow_on_error", True)
    return value


def result_key(step: Any) -> str:
    method = getattr(step, "result_key", None)
    if callable(method):
        return str(method())
    return f"{step_id(step)}.result"


def output_buffer_key(step: Any) -> str:
    method = getattr(step, "output_buffer_key", None)
    if callable(method):
        return str(method())
    return f"{step_id(step)}.output"


def buffer_read(buffer: Any, key: str) -> Any:
    read = getattr(buffer, "read", None)
    if callable(read):
        return read(key)
    return buffer[key]


def buffer_write(
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


def workflow_run_id(buffer: Any, configured_run_id: str | None) -> str:
    for source in (buffer, getattr(buffer, "buffer", None)):
        value = getattr(source, "run_id", None)
        if value:
            return str(value)
    return configured_run_id or "workflow-run"


def trace_id(buffer: Any, trace_context: Any) -> str | None:
    for source in (buffer, getattr(buffer, "buffer", None), trace_context):
        value = getattr(source, "trace_id", None)
        if value:
            return str(value)
    return None
