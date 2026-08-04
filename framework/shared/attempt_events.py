from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from framework.shared.attempts import AdmissionResult, AttemptContext


_DEADLINE_FIELDS = (
    "now_monotonic",
    "requested_until",
    "parent_available_until",
    "root_available_until",
    "completion_until",
    "effective_deadline",
    "execution_window_seconds",
    "min_start_window_seconds",
    "cancellation_grace_seconds",
    "completion_reserve_seconds",
)


def attempt_rejection_event_payload(
    *,
    execution_id: str,
    operation_id: str,
    operation_kind: str,
    idempotency_key: str,
    reason_code: str,
    admission: AdmissionResult,
) -> dict[str, Any]:
    details = dict(admission.details)
    return {
        "execution_id": execution_id,
        "operation_id": operation_id,
        "operation_kind": operation_kind,
        "idempotency_key": idempotency_key,
        "started": False,
        "reason_code": reason_code,
        "deadline_calculation": _deadline_calculation(details),
        "local_budget": _local_budget_snapshot(details),
        "root_retry_credits": _retry_credit_snapshot(details),
    }


def attempt_started_event_payload(
    *,
    execution_id: str,
    context: AttemptContext,
) -> dict[str, Any]:
    return _started_identity_payload(
        execution_id=execution_id,
        context=context,
    )


def attempt_terminal_event_payload(
    *,
    execution_id: str,
    context: AttemptContext,
    state: str,
    reason_code: str | None,
    termination_confirmed: bool,
    indeterminate: bool,
    elapsed_seconds: float,
) -> dict[str, Any]:
    return {
        **_started_identity_payload(
            execution_id=execution_id,
            context=context,
        ),
        "state": state,
        "reason_code": reason_code,
        "termination_confirmed": bool(termination_confirmed),
        "indeterminate": bool(indeterminate),
        "elapsed_seconds": max(0.0, float(elapsed_seconds)),
    }


def _started_identity_payload(
    *,
    execution_id: str,
    context: AttemptContext,
) -> dict[str, Any]:
    details = dict(context.admission_details)
    return {
        "execution_id": execution_id,
        "operation_id": context.operation_id or context.idempotency_key,
        "operation_kind": context.operation_kind,
        "idempotency_key": context.idempotency_key,
        "started": True,
        "attempt_id": context.attempt_id,
        "local_attempt_no": context.local_attempt_no,
        "retry_credit_id": context.retry_credit_id,
        "parent_attempt_id": context.parent_attempt_id,
        "deadline_calculation": _deadline_calculation(details),
        "local_budget": _local_budget_snapshot(details),
        "root_retry_credits": _retry_credit_snapshot(details),
    }


def _deadline_calculation(details: Mapping[str, Any]) -> dict[str, Any]:
    values = {field_name: details.get(field_name) for field_name in _DEADLINE_FIELDS}
    for field_name in (
        "min_start_window_seconds",
        "cancellation_grace_seconds",
        "completion_reserve_seconds",
    ):
        if values[field_name] is None:
            values[field_name] = 0.0
    return values


def _local_budget_snapshot(details: Mapping[str, Any]) -> dict[str, int]:
    snapshot = details.get("local_budget")
    if not isinstance(snapshot, Mapping):
        raise ValueError("attempt diagnostics are missing local_budget")
    return {
        "max_attempts": int(snapshot["max_attempts"]),
        "used_attempts": int(snapshot["used_attempts"]),
        "remaining_attempts": int(snapshot["remaining_attempts"]),
    }


def _retry_credit_snapshot(details: Mapping[str, Any]) -> dict[str, int]:
    snapshot = details.get("root_retry_credits")
    if not isinstance(snapshot, Mapping):
        raise ValueError("attempt diagnostics are missing root_retry_credits")
    return {
        "max_total_retries": int(snapshot["max_total_retries"]),
        "used_retries": int(snapshot["used_retries"]),
        "remaining_retries": int(snapshot["remaining_retries"]),
    }


__all__ = [
    "attempt_rejection_event_payload",
    "attempt_started_event_payload",
    "attempt_terminal_event_payload",
]
