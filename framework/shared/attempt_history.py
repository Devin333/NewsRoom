from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
import math
from typing import Any

ATTEMPT_HISTORY_PROJECTION_SCHEMA = "attempt-history-projection/v1"
ATTEMPT_EVENT_DATA_SCHEMA = "newsroom.attempt-event/v1"
ATTEMPT_EVENT_TYPES = frozenset(
    {
        "attempt_admission_rejected",
        "attempt_started",
        "attempt_terminal",
    }
)
LEGACY_ATTEMPT_SEMANTICS = "legacy-shared-attempt-budget/v1"
SCOPE_AWARE_ATTEMPT_SEMANTICS = "scope-aware-attempt/v1"

_LEGACY_ATTEMPT_EVENT_TYPES = frozenset(
    {
        "attempt_started",
        "attempt_finished",
        "attempt_failed",
        "attempt_timeout",
        "step_started",
        "step_failed",
        "step_timeout",
        "tool_started",
        "tool_failed",
        "tool_timeout",
        "worker_task_started",
        "worker_task_finished",
        "parallel_branch_started",
        "parallel_branch_finished",
    }
)
_LEGACY_FIELD_NAMES = (
    "fencing_token",
    "max_total_attempts",
    "attempt_budget",
    "budget",
)
_LEGACY_FIELD_PATHS = (
    (),
    ("outcome",),
    ("result",),
    ("error",),
    ("error_envelope", "details"),
)
_DEADLINE_FIELDS = frozenset(
    {
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
    }
)
_LOCAL_BUDGET_FIELDS = frozenset(
    {"max_attempts", "used_attempts", "remaining_attempts"}
)
_ROOT_RETRY_FIELDS = frozenset(
    {"max_total_retries", "used_retries", "remaining_retries"}
)


@dataclass(frozen=True, slots=True)
class AttemptHistoryProjection:
    """Read-only diagnostic projection; never executable replay input."""

    source_event_type: str
    source_data_schema: str | None
    source_event_id: str | None
    source_sequence: int | None
    semantics: str
    execution_id: str | None = None
    operation_id: str | None = None
    operation_kind: str | None = None
    idempotency_key: str | None = None
    attempt_id: str | None = None
    local_attempt_no: int | None = None
    retry_credit_id: str | None = None
    parent_attempt_id: str | None = None
    started: bool | None = None
    state: str | None = None
    reason_code: str | None = None
    deadline_calculation: dict[str, Any] = field(default_factory=dict)
    local_budget: dict[str, Any] = field(default_factory=dict)
    root_retry_credits: dict[str, Any] = field(default_factory=dict)
    termination_confirmed: bool | None = None
    indeterminate: bool | None = None
    elapsed_seconds: float | None = None
    legacy_fields: dict[str, Any] = field(default_factory=dict)
    projection_schema: str = field(
        default=ATTEMPT_HISTORY_PROJECTION_SCHEMA,
        init=False,
    )
    live_replay_permitted: bool = field(default=False, init=False)

    @property
    def legacy(self) -> bool:
        return self.semantics == LEGACY_ATTEMPT_SEMANTICS

    def to_dict(self) -> dict[str, Any]:
        return {
            "projection_schema": self.projection_schema,
            "source_event_type": self.source_event_type,
            "source_data_schema": self.source_data_schema,
            "source_event_id": self.source_event_id,
            "source_sequence": self.source_sequence,
            "semantics": self.semantics,
            "execution_id": self.execution_id,
            "operation_id": self.operation_id,
            "operation_kind": self.operation_kind,
            "idempotency_key": self.idempotency_key,
            "attempt_id": self.attempt_id,
            "local_attempt_no": self.local_attempt_no,
            "retry_credit_id": self.retry_credit_id,
            "parent_attempt_id": self.parent_attempt_id,
            "started": self.started,
            "state": self.state,
            "reason_code": self.reason_code,
            "deadline_calculation": dict(self.deadline_calculation),
            "local_budget": dict(self.local_budget),
            "root_retry_credits": dict(self.root_retry_credits),
            "termination_confirmed": self.termination_confirmed,
            "indeterminate": self.indeterminate,
            "elapsed_seconds": self.elapsed_seconds,
            "legacy_fields": dict(self.legacy_fields),
            "live_replay_permitted": False,
        }


def decode_attempt_history(event: Any) -> AttemptHistoryProjection | None:
    """Decode one new or legacy attempt record without invoking live runtime code."""

    source = _event_source(event)
    event_type = source["event_type"]
    payload = source["payload"]
    data_schema = source["data_schema"]
    if data_schema == ATTEMPT_EVENT_DATA_SCHEMA:
        if event_type not in ATTEMPT_EVENT_TYPES:
            raise ValueError(
                "attempt event schema cannot be used by an unrelated event type"
            )
        return _decode_scope_aware(source, payload)

    if event_type not in _LEGACY_ATTEMPT_EVENT_TYPES:
        return None
    legacy_fields = _legacy_fields(payload)
    if not legacy_fields:
        return None
    return AttemptHistoryProjection(
        source_event_type=event_type,
        source_data_schema=data_schema,
        source_event_id=source["event_id"],
        source_sequence=source["sequence"],
        semantics=LEGACY_ATTEMPT_SEMANTICS,
        execution_id=_optional_text(payload.get("execution_id") or payload.get("run_id")),
        operation_id=_first_text(payload, "operation_id", "step_id", "tool_call_id"),
        operation_kind=_optional_text(payload.get("operation_kind")),
        idempotency_key=_optional_text(payload.get("idempotency_key")),
        attempt_id=_optional_text(payload.get("attempt_id")),
        local_attempt_no=_optional_positive_int(
            payload.get("local_attempt_no") or payload.get("attempt_no")
        ),
        started=_optional_bool(payload.get("started")),
        state=_first_text(payload, "state", "status"),
        reason_code=_optional_text(payload.get("reason_code")),
        legacy_fields=legacy_fields,
    )


def decode_attempt_history_many(
    events: Iterable[Any],
) -> tuple[AttemptHistoryProjection, ...]:
    projections: list[AttemptHistoryProjection] = []
    for event in events:
        projection = decode_attempt_history(event)
        if projection is not None:
            projections.append(projection)
    return tuple(projections)


def _decode_scope_aware(
    source: dict[str, Any],
    payload: Mapping[str, Any],
) -> AttemptHistoryProjection:
    started = payload.get("started")
    if not isinstance(started, bool):
        raise ValueError("scope-aware attempt history requires boolean started")
    local_attempt_no = _optional_positive_int(payload.get("local_attempt_no"))
    attempt_id = _optional_text(payload.get("attempt_id"))
    if started and (attempt_id is None or local_attempt_no is None):
        raise ValueError("started attempt history requires attempt identity")
    if not started and (attempt_id is not None or local_attempt_no is not None):
        raise ValueError("rejected attempt history must not contain attempt identity")
    return AttemptHistoryProjection(
        source_event_type=source["event_type"],
        source_data_schema=source["data_schema"],
        source_event_id=source["event_id"],
        source_sequence=source["sequence"],
        semantics=SCOPE_AWARE_ATTEMPT_SEMANTICS,
        execution_id=_required_text(payload.get("execution_id"), "execution_id"),
        operation_id=_required_text(payload.get("operation_id"), "operation_id"),
        operation_kind=_required_text(
            payload.get("operation_kind"),
            "operation_kind",
        ),
        idempotency_key=_required_text(
            payload.get("idempotency_key"),
            "idempotency_key",
        ),
        attempt_id=attempt_id,
        local_attempt_no=local_attempt_no,
        retry_credit_id=_optional_text(payload.get("retry_credit_id")),
        parent_attempt_id=_optional_text(payload.get("parent_attempt_id")),
        started=started,
        state=_optional_text(payload.get("state")),
        reason_code=_optional_text(payload.get("reason_code")),
        deadline_calculation=_known_mapping(
            payload.get("deadline_calculation"),
            field_name="deadline_calculation",
            allowed_fields=_DEADLINE_FIELDS,
        ),
        local_budget=_known_mapping(
            payload.get("local_budget"),
            field_name="local_budget",
            allowed_fields=_LOCAL_BUDGET_FIELDS,
        ),
        root_retry_credits=_known_mapping(
            payload.get("root_retry_credits"),
            field_name="root_retry_credits",
            allowed_fields=_ROOT_RETRY_FIELDS,
        ),
        termination_confirmed=_optional_bool(
            payload.get("termination_confirmed")
        ),
        indeterminate=_optional_bool(payload.get("indeterminate")),
        elapsed_seconds=_optional_nonnegative_float(
            payload.get("elapsed_seconds")
        ),
    )


def _event_source(event: Any) -> dict[str, Any]:
    if isinstance(event, Mapping):
        raw = dict(event)
        nested = raw.get("event")
        if isinstance(nested, Mapping):
            nested_payload = dict(nested)
            return {
                "event_type": _required_text(
                    nested_payload.get("event_type"),
                    "event_type",
                ),
                "payload": _mapping(nested_payload.get("payload")),
                "data_schema": _optional_text(
                    raw.get("data_schema")
                    or nested_payload.get("data_schema")
                    or nested_payload.get("schema_version")
                ),
                "event_id": _optional_text(raw.get("event_id")),
                "sequence": _optional_positive_int(
                    raw.get("stream_sequence") or raw.get("sequence")
                ),
            }
        return {
            "event_type": _required_text(raw.get("event_type"), "event_type"),
            "payload": _mapping(raw.get("payload")),
            "data_schema": _optional_text(
                raw.get("data_schema") or raw.get("schema_version")
            ),
            "event_id": _optional_text(raw.get("event_id")),
            "sequence": _optional_positive_int(
                raw.get("stream_sequence") or raw.get("sequence")
            ),
        }

    compat_event = getattr(event, "event", None)
    if compat_event is not None:
        return {
            "event_type": _required_text(
                getattr(compat_event, "event_type", None),
                "event_type",
            ),
            "payload": _mapping(getattr(compat_event, "payload", None)),
            "data_schema": _optional_text(
                getattr(event, "data_schema", None)
                or getattr(compat_event, "data_schema", None)
                or getattr(compat_event, "schema_version", None)
            ),
            "event_id": _optional_text(getattr(event, "event_id", None)),
            "sequence": _optional_positive_int(
                getattr(event, "stream_sequence", None)
                or getattr(event, "sequence", None)
            ),
        }
    return {
        "event_type": _required_text(getattr(event, "event_type", None), "event_type"),
        "payload": _mapping(getattr(event, "payload", None)),
        "data_schema": _optional_text(
            getattr(event, "data_schema", None)
            or getattr(event, "schema_version", None)
        ),
        "event_id": _optional_text(getattr(event, "event_id", None)),
        "sequence": _optional_positive_int(
            getattr(event, "stream_sequence", None)
            or getattr(event, "sequence", None)
            or getattr(event, "line_number", None)
        ),
    }


def _legacy_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for path_parts in _LEGACY_FIELD_PATHS:
        current: Any = payload
        for path_part in path_parts:
            if not isinstance(current, Mapping):
                current = None
                break
            current = current.get(path_part)
        if not isinstance(current, Mapping):
            continue
        path = ".".join(("payload", *path_parts))
        for field_name in _LEGACY_FIELD_NAMES:
            if field_name in current:
                found[f"{path}.{field_name}"] = _legacy_value(current[field_name])
    return dict(sorted(found.items()))


def _known_mapping(
    value: Any,
    *,
    field_name: str,
    allowed_fields: frozenset[str],
) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"attempt history {field_name} must be an object")
    unknown = set(value) - allowed_fields
    if unknown:
        raise ValueError(
            f"attempt history {field_name} contains unknown fields: "
            + ", ".join(sorted(str(item) for item in unknown))
        )
    return {str(key): item for key, item in value.items()}


def _legacy_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        allowed = {
            key: item
            for key, item in value.items()
            if key in {"max_attempts", "used", "remaining"}
            and (item is None or isinstance(item, (bool, int, float, str)))
        }
        return dict(sorted(allowed.items()))
    return type(value).__name__


def _mapping(value: Any) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError("attempt history payload must be an object")
    return value


def _required_text(value: Any, field_name: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise ValueError(f"{field_name} is required")
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_text(payload: Mapping[str, Any], *field_names: str) -> str | None:
    for field_name in field_names:
        value = _optional_text(payload.get(field_name))
        if value is not None:
            return value
    return None


def _optional_positive_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("attempt history sequence fields must be positive integers")
    return value


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError("attempt history started must be a boolean")
    return value


def _optional_nonnegative_float(value: Any) -> float | None:
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < 0
    ):
        raise ValueError(
            "attempt history elapsed_seconds must be finite and non-negative"
        )
    return float(value)


__all__ = [
    "ATTEMPT_HISTORY_PROJECTION_SCHEMA",
    "LEGACY_ATTEMPT_SEMANTICS",
    "SCOPE_AWARE_ATTEMPT_SEMANTICS",
    "AttemptHistoryProjection",
    "decode_attempt_history",
    "decode_attempt_history_many",
]
