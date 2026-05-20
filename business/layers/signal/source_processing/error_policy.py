from __future__ import annotations

from typing import Any

from business.foundation.models.source import SourceErrorPolicyReport


def build_source_error_policy_report(source_errors: list[Any]) -> SourceErrorPolicyReport:
    rows: list[dict[str, Any]] = []
    errors_by_type: dict[str, int] = {}

    for error in source_errors:
        error_type = str(_value(error, "error_type") or "unknown")
        retryable = _bool_value(_value(error, "retryable"), default=True)
        metadata = _metadata(error)
        health_affecting = _bool_value(metadata.get("source_health_affecting"), default=True)
        workflow_blocking = _bool_value(metadata.get("workflow_blocking"), default=False)
        operator_action_required = _bool_value(
            metadata.get("operator_action_required"),
            default=False,
        )
        errors_by_type[error_type] = errors_by_type.get(error_type, 0) + 1
        rows.append(
            {
                "source_id": _value(error, "source_id"),
                "source_name": _value(error, "source_name"),
                "error_type": error_type,
                "retryable": retryable,
                "source_health_affecting": health_affecting,
                "workflow_blocking": workflow_blocking,
                "operator_action_required": operator_action_required,
            }
        )

    return SourceErrorPolicyReport(
        total_error_count=len(rows),
        retryable_error_count=sum(1 for row in rows if row["retryable"]),
        non_retryable_error_count=sum(1 for row in rows if not row["retryable"]),
        health_affecting_error_count=sum(1 for row in rows if row["source_health_affecting"]),
        workflow_blocking_error_count=sum(1 for row in rows if row["workflow_blocking"]),
        operator_action_required_count=sum(1 for row in rows if row["operator_action_required"]),
        errors_by_type=errors_by_type,
        rows=rows,
    )


def _metadata(value: Any) -> dict[str, Any]:
    metadata = _value(value, "metadata")
    return dict(metadata) if isinstance(metadata, dict) else {}


def _value(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _bool_value(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}
