from __future__ import annotations

import copy
import dis
import inspect
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import CodeType, FunctionType, ModuleType
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from jsonschema.exceptions import SchemaError, ValidationError
from jsonschema.validators import validator_for

from framework.events.errors import (
    EventContextConflictError,
    EventSchemaError,
    EventSchemaValidationError,
    EventUnknownSchemaError,
    EventQuarantineError,
    EventUpcastError,
)
from framework.events.schema.policy import (
    FieldDisposition,
    SensitivityPolicy,
    WholeDocumentReferenceDisposition,
)
from framework.shared.time import ensure_utc

if TYPE_CHECKING:
    from framework.events.canonical import BusinessContext


PayloadValidator = Callable[[Mapping[str, Any]], None]
EventUpcaster = Callable[[Mapping[str, Any]], Mapping[str, Any]]


_BUSINESS_CONTEXT_FIELDS = (
    "run_id",
    "workflow_id",
    "step_id",
    "task_id",
    "agent_id",
    "tool_call_id",
    "request_id",
)


SUPPORTED_HISTORICAL_ENVELOPE_SCHEMAS = frozenset(
    {
        "newsroom.event-envelope/v2",
        "newsroom.event.v1",
        "newsroom.event_envelope.v1",
        "newsroom.event_record.v1",
    }
)


@dataclass(frozen=True)
class HistoricalSchemaResolution:
    event_type: str
    source_data_schema: str
    data_schema: str
    occurred_at: datetime
    payload: Mapping[str, Any]
    applied_upcasters: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_type", _required_text(self.event_type, "event_type"))
        object.__setattr__(
            self,
            "source_data_schema",
            _required_text(self.source_data_schema, "source_data_schema"),
        )
        object.__setattr__(self, "data_schema", _required_text(self.data_schema, "data_schema"))
        if not isinstance(self.occurred_at, datetime):
            raise TypeError("occurred_at must be a datetime")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        object.__setattr__(self, "occurred_at", ensure_utc(self.occurred_at))
        object.__setattr__(self, "payload", _freeze_mapping(self.payload))
        if isinstance(self.applied_upcasters, (str, bytes)):
            raise TypeError("applied_upcasters must be a sequence of strings")
        object.__setattr__(
            self,
            "applied_upcasters",
            tuple(_required_text(item, "applied_upcaster") for item in self.applied_upcasters),
        )

    def payload_copy(self) -> dict[str, Any]:
        return _thaw_mapping(self.payload)


@dataclass(frozen=True)
class EventSchemaRegistration:
    event_type: str
    data_schema: str
    json_schema: Mapping[str, Any]
    sensitivity_policy: SensitivityPolicy = field(default_factory=SensitivityPolicy)
    upcast_to: str | None = None
    upcaster: EventUpcaster | None = None
    custom_validator: PayloadValidator | None = None
    current: bool = False
    authoritative_context_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        event_type = _required_text(self.event_type, "event_type")
        data_schema = _required_text(self.data_schema, "data_schema")
        upcast_to = _optional_text(self.upcast_to)
        if (upcast_to is None) != (self.upcaster is None):
            raise ValueError("upcast_to and upcaster must be configured together")
        if not isinstance(self.current, bool):
            raise TypeError("current must be a bool")
        if isinstance(self.authoritative_context_fields, (str, bytes)):
            raise TypeError("authoritative_context_fields must be a sequence")
        context_fields = tuple(self.authoritative_context_fields)
        if len(context_fields) != len(set(context_fields)):
            raise EventSchemaError("authoritative context fields must be unique")
        unknown_context_fields = sorted(
            set(context_fields) - set(_BUSINESS_CONTEXT_FIELDS)
        )
        if unknown_context_fields:
            raise EventSchemaError(
                "unknown authoritative context field: " + unknown_context_fields[0]
            )
        if not isinstance(self.sensitivity_policy, SensitivityPolicy):
            raise TypeError("sensitivity_policy must be SensitivityPolicy")
        if upcast_to is not None:
            if self.current:
                raise EventSchemaError("a current event schema cannot declare an upcaster")
            _validate_adjacent_schema_versions(data_schema, upcast_to)
            _validate_upcaster_purity(self.upcaster, event_type, data_schema)
        if self.custom_validator is not None:
            _validate_custom_validator_purity(
                self.custom_validator,
                event_type,
                data_schema,
            )
        if not isinstance(self.json_schema, Mapping):
            raise TypeError("json_schema must be a mapping")
        schema = copy.deepcopy(dict(self.json_schema))
        try:
            validator_cls = validator_for(schema)
            validator_cls.check_schema(schema)
        except SchemaError as exc:
            raise EventSchemaError(
                f"invalid JSON schema for {event_type} ({data_schema})"
            ) from exc
        object.__setattr__(self, "event_type", event_type)
        object.__setattr__(self, "data_schema", data_schema)
        object.__setattr__(self, "upcast_to", upcast_to)
        object.__setattr__(self, "json_schema", _freeze_mapping(schema))
        object.__setattr__(
            self,
            "authoritative_context_fields",
            context_fields,
        )

    def schema_copy(self) -> dict[str, Any]:
        return _thaw_mapping(self.json_schema)


class EventSchemaCatalog:
    """Deterministic registry for event payload schemas and adjacent upcasters."""

    def __init__(self) -> None:
        self._registrations: dict[tuple[str, str], EventSchemaRegistration] = {}
        self._current: dict[str, str] = {}

    def register(self, registration: EventSchemaRegistration) -> None:
        key = (registration.event_type, registration.data_schema)
        if key in self._registrations:
            raise EventSchemaError(
                f"duplicate event schema registration: {registration.event_type} "
                f"({registration.data_schema})"
            )
        if registration.current and registration.event_type in self._current:
            raise EventSchemaError(
                f"multiple current schemas for event type: {registration.event_type}"
            )
        if registration.upcast_to == registration.data_schema:
            raise EventSchemaError("event schema cannot upcast to itself")
        self._registrations[key] = registration
        if registration.current:
            self._current[registration.event_type] = registration.data_schema

    def get(self, event_type: str, data_schema: str) -> EventSchemaRegistration:
        key = (
            _required_text(event_type, "event_type"),
            _required_text(data_schema, "data_schema"),
        )
        registration = self._registrations.get(key)
        if registration is None:
            raise EventUnknownSchemaError(*key)
        return registration

    def current_schema(self, event_type: str) -> str:
        event_type = _required_text(event_type, "event_type")
        current = self._current.get(event_type)
        if current is None:
            raise EventUnknownSchemaError(event_type, "<current>")
        return current

    def registrations(self) -> tuple[EventSchemaRegistration, ...]:
        return tuple(
            self._registrations[key]
            for key in sorted(self._registrations, key=lambda item: (item[0], item[1]))
        )

    def validate(
        self,
        event_type: str,
        data_schema: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        registration = self.get(event_type, data_schema)
        canonicalization_failed = False
        snapshot: dict[str, Any] | None = None
        try:
            snapshot = _thaw_mapping(_freeze_mapping(payload))
        except (TypeError, ValueError):
            canonicalization_failed = True
        if canonicalization_failed:
            raise EventSchemaValidationError(
                event_type=registration.event_type,
                data_schema=registration.data_schema,
                path="$",
                rule="canonical_json",
            ) from None
        if snapshot is None:  # pragma: no cover - freeze returns or raises
            raise AssertionError("schema payload canonicalization returned no value")
        schema = registration.schema_copy()
        validator_cls = validator_for(schema)
        validator = validator_cls(schema)
        first_error = next(
            iter(
                sorted(
                    validator.iter_errors(snapshot),
                    key=lambda item: (_json_path(item), str(item.validator)),
                )
            ),
            None,
        )
        if first_error is not None:
            raise _validation_error(registration, first_error)
        if registration.custom_validator is not None:
            custom_failure: EventSchemaValidationError | None = None
            try:
                _run_pure_validator(registration.custom_validator, snapshot)
            except EventSchemaValidationError as error:
                custom_failure = EventSchemaValidationError(
                    event_type=error.event_type,
                    data_schema=error.data_schema,
                    path=error.path,
                    rule=error.rule,
                )
            except Exception:
                custom_failure = EventSchemaValidationError(
                    event_type=registration.event_type,
                    data_schema=registration.data_schema,
                    path="$",
                    rule="custom",
                )
            if custom_failure is not None:
                raise custom_failure from None
        return snapshot

    def prepare_publish_payload(
        self,
        event_type: str,
        data_schema: str,
        payload: Mapping[str, Any],
        *,
        business_context: BusinessContext,
    ) -> dict[str, Any]:
        """Return the detached canonical payload accepted for publication.

        Workflow compatibility inputs may repeat fields that are authoritative
        in ``BusinessContext``. Equal duplicates are removed before schema
        validation; a conflicting or payload-only value fails with the typed
        context error instead of silently choosing one authority.
        """

        from framework.events.canonical import BusinessContext

        registration = self.get(event_type, data_schema)
        if not isinstance(business_context, BusinessContext):
            raise TypeError("business_context must be BusinessContext")
        try:
            snapshot = _thaw_mapping(_freeze_mapping(payload))
        except (TypeError, ValueError):
            raise EventSchemaValidationError(
                event_type=registration.event_type,
                data_schema=registration.data_schema,
                path="$",
                rule="canonical_json",
            ) from None

        for field_name in registration.authoritative_context_fields:
            if field_name not in snapshot:
                continue
            if snapshot[field_name] != getattr(business_context, field_name):
                raise EventContextConflictError(field_name)
            del snapshot[field_name]

        return self.validate(event_type, data_schema, snapshot)

    def upcast(
        self,
        event_type: str,
        data_schema: str,
        payload: Mapping[str, Any],
        *,
        target_schema: str | None = None,
    ) -> tuple[str, dict[str, Any], tuple[str, ...]]:
        desired = target_schema or self.current_schema(event_type)
        current_schema = str(data_schema)
        current_payload = self.validate(event_type, current_schema, payload)
        applied: list[str] = []
        visited: set[str] = set()

        while current_schema != desired:
            if current_schema in visited:
                raise EventUpcastError(
                    f"event upcast cycle: {event_type} ({current_schema})"
                )
            visited.add(current_schema)
            registration = self.get(event_type, current_schema)
            if registration.upcast_to is None or registration.upcaster is None:
                raise EventUpcastError(
                    f"no event upcast path: {event_type} ({current_schema} -> {desired})"
                )
            upcaster_failed = False
            next_payload: dict[str, Any] | None = None
            try:
                next_payload = _run_pure_upcaster(registration.upcaster, current_payload)
            except Exception:
                upcaster_failed = True
            if upcaster_failed or next_payload is None:
                raise EventUpcastError(
                    f"event upcaster failed: {event_type} ({current_schema})"
                ) from None
            next_schema = registration.upcast_to
            output_validation_failed = False
            try:
                self.get(event_type, next_schema)
                current_payload = self.validate(event_type, next_schema, next_payload)
            except (EventUnknownSchemaError, EventSchemaValidationError):
                output_validation_failed = True
            if output_validation_failed:
                raise EventUpcastError(
                    f"event upcaster output failed validation: "
                    f"{event_type} ({current_schema} -> {next_schema})"
                ) from None
            applied.append(f"{current_schema}->{next_schema}")
            current_schema = next_schema

        return current_schema, current_payload, tuple(applied)

    def resolve_historical(
        self,
        event_type: str,
        data_schema: str,
        payload: Mapping[str, Any],
        *,
        occurred_at: str | datetime | None,
        envelope_schema: str | None = None,
        source: str | None = None,
        target_schema: str | None = None,
    ) -> HistoricalSchemaResolution:
        """Resolve a historical payload without inventing time or schema identity.

        The migration layer persists the quarantine record.  This method owns the
        deterministic classification used by import, replay, and verification.
        It intentionally returns no raw diagnostic or source payload on failure.
        """

        if envelope_schema is not None:
            normalized_envelope = _required_text(envelope_schema, "envelope_schema")
            if normalized_envelope not in SUPPORTED_HISTORICAL_ENVELOPE_SCHEMAS:
                raise EventQuarantineError("unknown_envelope_schema", source=source)

        if occurred_at is None or (isinstance(occurred_at, str) and not occurred_at.strip()):
            raise EventQuarantineError("missing_occurred_at", source=source)
        if not isinstance(occurred_at, (str, datetime)):
            raise EventQuarantineError("invalid_occurred_at", source=source)
        historical_time_invalid = False
        parsed_time: datetime | None = None
        try:
            parsed_time = _parse_historical_time(occurred_at)
        except (TypeError, ValueError, OverflowError):
            historical_time_invalid = True
        if historical_time_invalid or parsed_time is None:
            raise EventQuarantineError("invalid_occurred_at", source=source) from None

        schema_is_unknown = False
        try:
            self.get(event_type, data_schema)
        except EventUnknownSchemaError:
            schema_is_unknown = True
        if schema_is_unknown:
            raise EventQuarantineError("unknown_data_schema", source=source) from None
        historical_failure: str | None = None
        resolution: tuple[str, dict[str, Any], tuple[str, ...]] | None = None
        try:
            resolution = self.upcast(
                event_type,
                data_schema,
                payload,
                target_schema=target_schema,
            )
        except EventSchemaValidationError:
            historical_failure = "schema_validation_failed"
        except EventUpcastError:
            historical_failure = "upcast_failed"
        if historical_failure is not None:
            raise EventQuarantineError(historical_failure, source=source) from None
        if resolution is None:  # pragma: no cover - upcast returns or raises
            raise AssertionError("historical schema resolution returned no value")
        resolved_schema, resolved_payload, applied = resolution

        return HistoricalSchemaResolution(
            event_type=_required_text(event_type, "event_type"),
            source_data_schema=_required_text(data_schema, "data_schema"),
            data_schema=resolved_schema,
            occurred_at=parsed_time,
            payload=resolved_payload,
            applied_upcasters=applied,
        )


WORKFLOW_EVENT_TYPES = (
    "workflow_started",
    "workflow_resumed",
    "checkpoint_restored",
    "checkpoint_created",
    "edge_evaluated",
    "edge_traversed",
    "edge_rejected",
    "human_review_decision_received",
    "human_review_requested",
    "human_review_paused",
    "human_review_approved",
    "human_review_rejected",
    "human_review_needs_changes",
    "agent_llm_stream_event",
    "memory_recall",
    "memory_write",
    "memory_consolidate",
    "workflow_succeeded",
    "workflow_blocked",
    "workflow_budget_exceeded",
    "workflow_failed",
    "workflow_timeout_exceeded",
    "workflow_cancelled",
    "workflow_loop_limit_exceeded",
    "workflow_paused",
    "step_started",
    "step_succeeded",
    "step_skipped",
    "step_paused",
    "step_blocked",
    "step_failed",
    "step_retry_scheduled",
    "step_timeout",
    "policy_violation",
    "runtime_safety_violation",
    "runner_capability_violation",
)

LEGACY_WORKFLOW_EVENT_ALIASES = (
    # Legacy typed aliases retained for the bounded migration release.
    "workflow_finished",
    "step_finished",
    "tool_called",
    "agent_iteration",
    "memory_recalled",
    "memory_written",
    "worker_task_started",
    "worker_task_finished",
)

WORKFLOW_EVENT_ALIASES = WORKFLOW_EVENT_TYPES + LEGACY_WORKFLOW_EVENT_ALIASES

WORKFLOW_OPERATION_EVENT_TYPES = (
    "run_operation_requested",
    "run_operation_applied",
    "run_operation_rejected",
    "run_operation_failed",
)

HARNESS_EVENT_ALIASES = (
    "run_created",
    "run_state_changed",
    "step_state_changed",
    "phase_recorded",
    "decision_recorded",
    "worker_called",
    "worker_result_recorded",
    "gate_evaluated",
    "checkpoint_created",
)

HARNESS_TRANSITION_EVENT_TYPE = "harness_transition_committed"
HARNESS_TRANSITION_DATA_SCHEMA = "newsroom.harness-transition/v1"


def default_event_schema_catalog() -> EventSchemaCatalog:
    catalog = EventSchemaCatalog()
    for event_type in WORKFLOW_EVENT_ALIASES:
        catalog.register(
            EventSchemaRegistration(
                event_type=event_type,
                data_schema="newsroom.workflow-event/v1",
                json_schema=_workflow_payload_schema(event_type),
                sensitivity_policy=_workflow_sensitivity_policy(event_type),
                current=True,
                authoritative_context_fields=_BUSINESS_CONTEXT_FIELDS,
            )
        )
    for event_type in WORKFLOW_OPERATION_EVENT_TYPES:
        catalog.register(
            EventSchemaRegistration(
                event_type=event_type,
                data_schema="newsroom.workflow-operation/v1",
                json_schema=_workflow_operation_payload_schema(event_type),
                sensitivity_policy=_workflow_operation_sensitivity_policy(),
                current=True,
                authoritative_context_fields=_BUSINESS_CONTEXT_FIELDS,
            )
        )
    for event_type in HARNESS_EVENT_ALIASES:
        catalog.register(
            EventSchemaRegistration(
                event_type=event_type,
                data_schema="newsroom.harness-event/v1",
                json_schema=_harness_payload_schema(event_type),
                sensitivity_policy=_harness_sensitivity_policy(event_type),
                # `checkpoint_created` is a legacy name shared with Workflow.
                # The producer adapter must pass its explicit data schema; the
                # Workflow alias remains the default during migration.
                current=event_type not in WORKFLOW_EVENT_ALIASES,
            )
        )
    catalog.register(
        EventSchemaRegistration(
            event_type=HARNESS_TRANSITION_EVENT_TYPE,
            data_schema=HARNESS_TRANSITION_DATA_SCHEMA,
            json_schema=_harness_transition_payload_schema(),
            sensitivity_policy=SensitivityPolicy(),
            current=True,
        )
    )
    return catalog


_TEXT = {"type": "string", "minLength": 1, "maxLength": 1024}
_NULLABLE_TEXT = {"type": ["string", "null"], "maxLength": 4096}
_OBJECT = {"type": "object", "maxProperties": 128}
_ARRAY_OF_TEXT = {"type": "array", "items": _TEXT, "maxItems": 4096}
_NONNEGATIVE_INTEGER = {"type": "integer", "minimum": 0}
_POSITIVE_INTEGER = {"type": "integer", "minimum": 1}
_NUMBER = {"type": "number"}
_NONNEGATIVE_NUMBER = {"type": "number", "minimum": 0}
_POSITIVE_NUMBER = {"type": "number", "exclusiveMinimum": 0}
_NULLABLE_POSITIVE_NUMBER = {
    "anyOf": [_POSITIVE_NUMBER, {"type": "null"}],
}
_BOOLEAN = {"type": "boolean"}
_WORKFLOW_TIMEOUT_POLICY_SOURCE = {
    "enum": [
        "policies.timeout_policy.timeout_seconds",
        "policies.resource_policy.max_runtime_seconds",
    ]
}
_WORKFLOW_OPERATION_TYPE = {
    "enum": [
        "cancel_run",
        "rerun_from_step",
        "resume_with_patch",
        "skip_step",
        "mark_blocked_resolved",
    ]
}
_CHECKSUM_TEXT = {
    "type": "string",
    "pattern": "^sha256:[0-9a-f]{64}$",
}
_ARRAY_OF_CHECKSUMS = {
    "type": "array",
    "items": _CHECKSUM_TEXT,
    "maxItems": 4096,
}
_HARNESS_GATE_RESULT = {
    "type": "object",
    "maxProperties": 6,
    "properties": {
        "gate": {"type": "string", "minLength": 1, "maxLength": 128},
        "passed": _BOOLEAN,
        "reason": _NULLABLE_TEXT,
        "details": _OBJECT,
        "diagnostics": _OBJECT,
        "result_ref": _CHECKSUM_TEXT,
    },
    "required": ["gate", "passed"],
    "additionalProperties": False,
}
_HARNESS_GATE_RESULTS = {
    "type": "array",
    "items": _HARNESS_GATE_RESULT,
    "maxItems": 256,
}
_HARNESS_PHASE_METADATA = {
    "type": "object",
    "maxProperties": 3,
    "properties": {
        "turn_count": _NONNEGATIVE_INTEGER,
        "worker_call_count": _NONNEGATIVE_INTEGER,
        "replan_count": _NONNEGATIVE_INTEGER,
    },
    "additionalProperties": False,
}
_HARNESS_DECISION_PAYLOAD = {
    "type": "object",
    "maxProperties": 9,
    "properties": {
        "approval_outcome": {"enum": ["approved", "cancelled"]},
        "backoff_seconds": {"type": "number", "minimum": 0},
        "max_turns": _NONNEGATIVE_INTEGER,
        "turn_count": _NONNEGATIVE_INTEGER,
        "gate_results": _HARNESS_GATE_RESULTS,
        "quality_verdict_ref": _CHECKSUM_TEXT,
        "worker_result_ref": _CHECKSUM_TEXT,
        "value_ref": _CHECKSUM_TEXT,
        "decision_payload_ref": _CHECKSUM_TEXT,
    },
    "required": ["decision_payload_ref"],
    "additionalProperties": False,
}
_HARNESS_STEP_METADATA = {
    "type": "object",
    "maxProperties": 4,
    "properties": {
        "approval_granted": _BOOLEAN,
        "rerouted": _BOOLEAN,
        "worker_result_ref": _CHECKSUM_TEXT,
        "metadata_ref": _CHECKSUM_TEXT,
    },
    "additionalProperties": False,
}

_HARNESS_TRANSITION_KINDS = (
    "initialize",
    "run_start",
    "plan_entry",
    "plan_exit",
    "execute_entry",
    "execute_exit",
    "verify_entry",
    "verify_exit",
    "replan_entry",
    "replan_exit",
    "retry",
    "route_to_repair",
    "route_to_step",
    "wait_for_approval",
    "approval_resume",
    "approval_cancel",
    "worker_result_committed",
    "step_success",
    "budget_exhaustion",
    "halt",
    "failure",
    "success",
    "cancel",
    "wait",
)
_HARNESS_TRANSITION_STEP_METADATA = {
    "type": "object",
    "maxProperties": 16,
    "properties": {
        "approval_granted": _BOOLEAN,
        "rerouted": _BOOLEAN,
        "activity_attempt": _POSITIVE_INTEGER,
        "activity_id": _TEXT,
        "activity_type": _TEXT,
        "activity_contract_version": _TEXT,
        "activity_idempotency_key": _TEXT,
        "activity_input_checksum": _CHECKSUM_TEXT,
        "activity_identity_scope_ref": _CHECKSUM_TEXT,
        "activity_worker_version": _TEXT,
        "activity_result_event_id": _TEXT,
        "worker_result_ref": _TEXT,
        "worker_status": {
            "enum": ["succeeded", "failed", "blocked", "waiting_approval"]
        },
        "omitted_metadata_ref": _CHECKSUM_TEXT,
        "omitted_metadata_count": _NONNEGATIVE_INTEGER,
    },
    "additionalProperties": False,
}
_HARNESS_TRANSITION_STEP_STATE = {
    "type": "object",
    "maxProperties": 10,
    "properties": {
        "step_id": _TEXT,
        "status": {
            "enum": [
                "pending",
                "planning",
                "plan_verified",
                "running",
                "verifying",
                "retrying",
                "replanning",
                "succeeded",
                "failed",
                "skipped",
                "waiting_approval",
                "halted",
            ]
        },
        "attempts": _NONNEGATIVE_INTEGER,
        "replans": _NONNEGATIVE_INTEGER,
        "has_output_ref": _BOOLEAN,
        "output_ref_checksum": _CHECKSUM_TEXT,
        "error_ref": _CHECKSUM_TEXT,
        "metadata": _HARNESS_TRANSITION_STEP_METADATA,
        "updated_at": _TEXT,
    },
    "required": [
        "step_id",
        "status",
        "attempts",
        "replans",
        "has_output_ref",
        "metadata",
        "updated_at",
    ],
    "additionalProperties": False,
}
_HARNESS_TRANSITION_STATE_METADATA = {
    "type": "object",
    "maxProperties": 24,
    "properties": {
        "repair_from_step_id": _TEXT,
        "evolution_epochs_used": _NONNEGATIVE_INTEGER,
        "candidates_used": _NONNEGATIVE_INTEGER,
        "patch_operations_used": _NONNEGATIVE_INTEGER,
        "eval_cases_used": _NONNEGATIVE_INTEGER,
        "sandbox_runs_used": _NONNEGATIVE_INTEGER,
        "outputs_ref": _CHECKSUM_TEXT,
        "outputs_count": _NONNEGATIVE_INTEGER,
        "plan_keys_ref": _CHECKSUM_TEXT,
        "plan_keys_count": _NONNEGATIVE_INTEGER,
        "claims_ref": _CHECKSUM_TEXT,
        "claims_count": _NONNEGATIVE_INTEGER,
        "questions_ref": _CHECKSUM_TEXT,
        "questions_count": _NONNEGATIVE_INTEGER,
        "terminal_reason_ref": _CHECKSUM_TEXT,
        "omitted_metadata_ref": _CHECKSUM_TEXT,
        "omitted_metadata_count": _NONNEGATIVE_INTEGER,
    },
    "additionalProperties": False,
}
_HARNESS_TRANSITION_STATE = {
    "type": "object",
    "maxProperties": 14,
    "properties": {
        "schema": {"const": "newsroom.harness-state-projection/v1"},
        "run_spec_checksum": _CHECKSUM_TEXT,
        "workflow_id": _TEXT,
        "workflow_checksum": _CHECKSUM_TEXT,
        "workflow_version": _TEXT,
        "status": {
            "enum": [
                "created",
                "running",
                "planning",
                "executing",
                "verifying",
                "replanning",
                "waiting_approval",
                "succeeded",
                "failed",
                "halted",
                "cancelled",
                "blocked",
            ]
        },
        "step_states": {
            "type": "array",
            "items": _HARNESS_TRANSITION_STEP_STATE,
            "maxItems": 1024,
        },
        "current_step_id": _NULLABLE_TEXT,
        "turn_count": _NONNEGATIVE_INTEGER,
        "replan_count": _NONNEGATIVE_INTEGER,
        "worker_call_count": _NONNEGATIVE_INTEGER,
        "metadata": _HARNESS_TRANSITION_STATE_METADATA,
        "updated_at": _TEXT,
    },
    "required": [
        "schema",
        "run_spec_checksum",
        "workflow_id",
        "workflow_checksum",
        "workflow_version",
        "status",
        "step_states",
        "current_step_id",
        "turn_count",
        "replan_count",
        "worker_call_count",
        "metadata",
        "updated_at",
    ],
    "additionalProperties": False,
}


def _payload_schema(
    *,
    properties: Mapping[str, Any] | None = None,
    required: tuple[str, ...] = (),
    additional_properties: bool = False,
    any_of: tuple[Mapping[str, Any], ...] = (),
    min_properties: int | None = None,
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "maxProperties": 128,
        "properties": copy.deepcopy(dict(properties or {})),
        "additionalProperties": additional_properties,
    }
    if required:
        schema["required"] = list(required)
    if any_of:
        schema["anyOf"] = [copy.deepcopy(dict(item)) for item in any_of]
    if min_properties is not None:
        schema["minProperties"] = min_properties
    return schema


def _workflow_payload_schema(event_type: str) -> dict[str, Any]:
    if event_type == "workflow_started":
        return _payload_schema(
            properties={
                "workflow_id": _TEXT,
                "workflow_version": _TEXT,
                "profile": _TEXT,
                "run_id": _TEXT,
                "topic": _TEXT,
            },
            any_of=(
                {"required": ["workflow_version", "profile"]},
                {"required": ["run_id"]},
            ),
        )
    if event_type == "workflow_resumed":
        return _payload_schema(
            properties={
                "workflow_id": _TEXT,
                "workflow_version": _TEXT,
                "profile": _TEXT,
                "checkpoint_id": _TEXT,
                "resume_metadata": _OBJECT,
            },
            required=("workflow_version", "profile", "checkpoint_id"),
        )
    if event_type in {"checkpoint_restored", "checkpoint_created"}:
        return _payload_schema(
            properties={
                "checkpoint_id": _TEXT,
                "current_step_ids": _ARRAY_OF_TEXT,
                "path": _ARRAY_OF_TEXT,
            },
            required=("checkpoint_id",),
        )
    if event_type in {"edge_evaluated", "edge_traversed", "edge_rejected"}:
        return _payload_schema(
            properties={
                "edge_id": _TEXT,
                "source_step_id": _TEXT,
                "target_step_id": _TEXT,
                "condition": _TEXT,
                "matched": _BOOLEAN,
                "condition_expr": _NULLABLE_TEXT,
            },
            required=(
                "edge_id",
                "source_step_id",
                "target_step_id",
                "condition",
                "matched",
            ),
        )
    if event_type in {
        "human_review_decision_received",
        "human_review_approved",
        "human_review_rejected",
        "human_review_needs_changes",
    }:
        return _payload_schema(
            properties={
                "decision": _TEXT,
                "actor_id": _NULLABLE_TEXT,
                "approval_id": _NULLABLE_TEXT,
                "request_id": _NULLABLE_TEXT,
            },
            required=("decision",),
        )
    if event_type == "human_review_requested":
        return _payload_schema(
            properties={
                "step_id": _TEXT,
                "request_id": _TEXT,
                "checkpoint_id": _TEXT,
            },
            required=("checkpoint_id",),
        )
    if event_type == "human_review_paused":
        return _payload_schema(
            properties={"step_id": _TEXT, "outcome": _OBJECT},
            required=("outcome",),
        )
    if event_type == "agent_llm_stream_event":
        return _payload_schema(
            properties={
                "step_id": _TEXT,
                "agent_id": _NULLABLE_TEXT,
                "iteration": {"type": ["integer", "null"], "minimum": 0},
                "sequence": {"type": ["integer", "null"], "minimum": 0},
                "stream_event_type": _NULLABLE_TEXT,
                "text_delta_chars": {"type": ["integer", "null"], "minimum": 0},
                "stream_event_ref": _CHECKSUM_TEXT,
            },
            required=("stream_event_ref",),
        )
    if event_type == "memory_recall":
        return _payload_schema(
            properties={
                "step_id": _TEXT,
                "status": _TEXT,
                "operation": {"const": "recall"},
                "result_count": _NONNEGATIVE_INTEGER,
                "memory_ids": _ARRAY_OF_TEXT,
                "context_token_estimate": _NONNEGATIVE_INTEGER,
            },
            required=(
                "status",
                "operation",
                "result_count",
                "memory_ids",
                "context_token_estimate",
            ),
        )
    if event_type == "memory_write":
        return _payload_schema(
            properties={
                "step_id": _TEXT,
                "status": _TEXT,
                "operation": {"const": "write"},
                "accepted_count": _NONNEGATIVE_INTEGER,
                "written_count": _NONNEGATIVE_INTEGER,
                "skipped_count": _NONNEGATIVE_INTEGER,
                "memory_ids": _ARRAY_OF_TEXT,
            },
            required=(
                "status",
                "operation",
                "accepted_count",
                "written_count",
                "skipped_count",
                "memory_ids",
            ),
        )
    if event_type == "memory_consolidate":
        return _payload_schema(
            properties={
                "step_id": _TEXT,
                "status": _TEXT,
                "operation": {"const": "consolidate"},
                "consolidated_count": _NONNEGATIVE_INTEGER,
                "skipped_count": _NONNEGATIVE_INTEGER,
                "memory_ids": _ARRAY_OF_TEXT,
                "source_memory_ids": _ARRAY_OF_TEXT,
            },
            required=(
                "status",
                "operation",
                "consolidated_count",
                "skipped_count",
                "memory_ids",
                "source_memory_ids",
            ),
        )
    if event_type == "workflow_succeeded":
        return _payload_schema(properties={"path": _ARRAY_OF_TEXT}, required=("path",))
    if event_type in {"workflow_blocked", "workflow_budget_exceeded", "workflow_failed"}:
        return _payload_schema(
            properties={
                "path": _ARRAY_OF_TEXT,
                "error": {"type": ["object", "null"]},
            },
            required=("path", "error"),
        )
    if event_type == "workflow_timeout_exceeded":
        return _payload_schema(
            properties={
                "run_id": _TEXT,
                "workflow_id": _TEXT,
                "step_id": _TEXT,
                "pending_step_id": _TEXT,
                "timeout_seconds": _POSITIVE_NUMBER,
                "elapsed_seconds": _NONNEGATIVE_NUMBER,
                "policy_source": _WORKFLOW_TIMEOUT_POLICY_SOURCE,
            },
            required=("timeout_seconds", "elapsed_seconds", "policy_source"),
        )
    if event_type == "workflow_cancelled":
        return _payload_schema(properties={"run_id": _TEXT})
    if event_type == "workflow_loop_limit_exceeded":
        return _payload_schema(
            properties={
                "step_id": _TEXT,
                "max_step_visits": _POSITIVE_INTEGER,
                "visit_count": _POSITIVE_INTEGER,
            },
            required=("max_step_visits", "visit_count"),
        )
    if event_type == "workflow_paused":
        return _payload_schema(
            properties={"reason": _TEXT, "step_id": _TEXT},
            required=("reason",),
        )
    if event_type == "step_started":
        return _payload_schema(
            properties={
                "step_id": _TEXT,
                "step_type": _TEXT,
                "attempt": _POSITIVE_INTEGER,
                "max_attempts": _POSITIVE_INTEGER,
            },
            required=("step_type", "attempt", "max_attempts"),
        )
    if event_type in {"step_succeeded", "step_skipped"}:
        return _payload_schema(
            properties={"step_id": _TEXT, "outputs": _ARRAY_OF_TEXT},
            required=("outputs",),
        )
    if event_type in {"step_paused", "step_blocked", "step_failed"}:
        return _payload_schema(
            properties={"step_id": _TEXT, "outcome": _OBJECT},
            required=("outcome",),
        )
    if event_type == "step_retry_scheduled":
        return _payload_schema(
            properties={
                "step_id": _TEXT,
                "attempt": _POSITIVE_INTEGER,
                "next_attempt": _POSITIVE_INTEGER,
                "max_attempts": _POSITIVE_INTEGER,
                "error_type": _NULLABLE_TEXT,
                "error_message": _NULLABLE_TEXT,
                "delay_seconds": {"type": "number", "minimum": 0},
            },
            required=("attempt", "next_attempt", "max_attempts", "delay_seconds"),
        )
    if event_type == "step_timeout":
        return _payload_schema(
            properties={
                "step_id": _TEXT,
                "attempt": _POSITIVE_INTEGER,
                "max_attempts": _POSITIVE_INTEGER,
                "timeout_seconds": {"type": "number", "exclusiveMinimum": 0},
                "on_timeout": _TEXT,
                "termination_confirmed": {"type": ["boolean", "null"]},
                "indeterminate": _BOOLEAN,
            },
            required=(
                "attempt",
                "max_attempts",
                "timeout_seconds",
                "on_timeout",
            ),
        )
    if event_type == "policy_violation":
        return _payload_schema(
            properties={
                "step_id": _TEXT,
                "code": _TEXT,
                "message": _TEXT,
                "policy": _TEXT,
                "limit": _NONNEGATIVE_NUMBER,
                "actual": _NONNEGATIVE_NUMBER,
                "metadata": _OBJECT,
                "resource_estimate": _OBJECT,
                "item_count": _NONNEGATIVE_INTEGER,
                "max_items": _NONNEGATIVE_INTEGER,
            },
            required=(
                "code",
                "message",
                "policy",
                "limit",
                "actual",
                "metadata",
                "resource_estimate",
            ),
        )
    if event_type == "runtime_safety_violation":
        return _payload_schema(
            properties={
                "step_id": _TEXT,
                "step_type": _TEXT,
                "policy": _TEXT,
                "code": _TEXT,
                "message": _TEXT,
                "metadata": _OBJECT,
            },
            required=("step_type", "policy", "code", "message", "metadata"),
        )
    if event_type == "runner_capability_violation":
        return _payload_schema(
            properties={
                "step_id": _TEXT,
                "step_type": _TEXT,
                "implementation": _NULLABLE_TEXT,
                "runner_id": _TEXT,
                "capability": {"enum": ["timeout", "retry", "resume"]},
                "message": _TEXT,
            },
            required=("message",),
            any_of=(
                {"required": ["step_type"]},
                {"required": ["runner_id", "capability"]},
            ),
        )
    if event_type in {"step_finished", "worker_task_started", "worker_task_finished"}:
        return _payload_schema(
            properties={"step_id": _TEXT},
            additional_properties=True,
        )
    if event_type in {
        "workflow_finished",
        "tool_called",
        "agent_iteration",
        "memory_recalled",
        "memory_written",
    }:
        return _payload_schema(additional_properties=True, min_properties=1)
    raise EventSchemaError(f"workflow event schema is not defined: {event_type}")


def _workflow_operation_payload_schema(event_type: str) -> dict[str, Any]:
    if event_type not in WORKFLOW_OPERATION_EVENT_TYPES:
        raise EventSchemaError(
            f"workflow operation event schema is not defined: {event_type}"
        )
    return _payload_schema(
        properties={
            "run_id": _TEXT,
            "operation_id": _TEXT,
            "operation_type": _WORKFLOW_OPERATION_TYPE,
            "actor_id": _NULLABLE_TEXT,
            "actor_type": _NULLABLE_TEXT,
            "reason": _NULLABLE_TEXT,
            "details": _OBJECT,
        },
        required=("operation_id", "operation_type", "details"),
    )


def _harness_transition_payload_schema() -> dict[str, Any]:
    return _payload_schema(
        properties={
            "transition_id": _TEXT,
            "from_version": _NONNEGATIVE_INTEGER,
            "state_version": _POSITIVE_INTEGER,
            "expected_last_sequence": _NONNEGATIVE_INTEGER,
            "transition_kind": {"enum": list(_HARNESS_TRANSITION_KINDS)},
            "state": _HARNESS_TRANSITION_STATE,
            "before_state_checksum": _CHECKSUM_TEXT,
            "after_state_checksum": _CHECKSUM_TEXT,
            "decision_ref": _CHECKSUM_TEXT,
            "gate_ref": _CHECKSUM_TEXT,
            "budget_ref": _CHECKSUM_TEXT,
            "activity_result_ref": _CHECKSUM_TEXT,
            "activity_result_event_id": _TEXT,
            "activity_id": _TEXT,
            "idempotency_key": _TEXT,
            "workflow_version": _TEXT,
            "workflow_checksum": _CHECKSUM_TEXT,
            "reducer_version": _TEXT,
            "policy_version": _TEXT,
            "schema_version": {"const": HARNESS_TRANSITION_DATA_SCHEMA},
        },
        required=(
            "transition_id",
            "from_version",
            "state_version",
            "expected_last_sequence",
            "transition_kind",
            "state",
            "before_state_checksum",
            "after_state_checksum",
            "workflow_version",
            "workflow_checksum",
            "reducer_version",
            "policy_version",
            "schema_version",
        ),
    )


def _harness_payload_schema(event_type: str) -> dict[str, Any]:
    if event_type == "run_created":
        return _payload_schema(
            properties={"projection_schema": {"const": "harness-safe-summary/v1"}},
        )
    if event_type == "run_state_changed":
        return _payload_schema(
            properties={
                "projection_schema": {"const": "harness-safe-summary/v1"},
                "status": {
                    "enum": [
                        "created",
                        "running",
                        "planning",
                        "executing",
                        "verifying",
                        "replanning",
                        "waiting_approval",
                        "succeeded",
                        "failed",
                        "halted",
                        "cancelled",
                        "blocked",
                    ]
                },
            },
            required=("status",),
        )
    if event_type == "step_state_changed":
        return _payload_schema(
            properties={
                "projection_schema": {"const": "harness-safe-summary/v1"},
                "step_id": _TEXT,
                "status": {
                    "enum": [
                        "pending",
                        "planning",
                        "plan_verified",
                        "running",
                        "verifying",
                        "retrying",
                        "replanning",
                        "succeeded",
                        "failed",
                        "skipped",
                        "waiting_approval",
                        "halted",
                    ]
                },
                "attempts": _NONNEGATIVE_INTEGER,
                "replans": _NONNEGATIVE_INTEGER,
                "output_ref": _NULLABLE_TEXT,
                "output_key_ref": _CHECKSUM_TEXT,
                "error": _NULLABLE_TEXT,
                "error_ref": _CHECKSUM_TEXT,
                "metadata": _HARNESS_STEP_METADATA,
                "updated_at": _TEXT,
            },
            required=("status", "attempts", "replans", "metadata"),
            any_of=(
                {"required": ["step_id", "updated_at"]},
                {"required": ["projection_schema"]},
            ),
        )
    if event_type == "phase_recorded":
        return _payload_schema(
            properties={
                "projection_schema": {"const": "harness-safe-summary/v1"},
                "phase": {"enum": ["plan", "execute", "verify", "replan", "halt"]},
                "boundary": {"enum": ["entry", "exit"]},
                "step_id": _TEXT,
                "input_refs": _ARRAY_OF_TEXT,
                "output_refs": _ARRAY_OF_TEXT,
                "input_ref_checksums": _ARRAY_OF_CHECKSUMS,
                "output_ref_checksums": _ARRAY_OF_CHECKSUMS,
                "gate_results": _HARNESS_GATE_RESULTS,
                "metadata": _HARNESS_PHASE_METADATA,
                "occurred_at": _TEXT,
                # Historical phase-transition payload retained during migration.
                "from_phase": _TEXT,
                "to_phase": _TEXT,
            },
            any_of=(
                {"required": ["phase", "step_id", "gate_results", "occurred_at"]},
                {
                    "required": [
                        "projection_schema",
                        "phase",
                        "boundary",
                        "input_ref_checksums",
                        "output_ref_checksums",
                        "gate_results",
                        "metadata",
                    ]
                },
                {"required": ["from_phase", "to_phase"]},
            ),
        )
    if event_type == "decision_recorded":
        return _payload_schema(
            properties={
                "projection_schema": {"const": "harness-safe-summary/v1"},
                "decision_type": {
                    "enum": [
                        "start_step",
                        "plan_step",
                        "execute_step",
                        "verify_step",
                        "complete_step",
                        "retry_step",
                        "replan_step",
                        "route_to_step",
                        "route_to_repair",
                        "wait_for_approval",
                        "resume_after_approval",
                        "fail_run",
                        "complete_run",
                        "cancel_run",
                        "block_run",
                        "halt_run",
                    ]
                },
                "run_id": _TEXT,
                "step_id": _NULLABLE_TEXT,
                "target_step_id": _NULLABLE_TEXT,
                "reason": _NULLABLE_TEXT,
                "reason_ref": _CHECKSUM_TEXT,
                "payload": _OBJECT,
                "decision_payload": _HARNESS_DECISION_PAYLOAD,
                "decided_by": {"const": "harness"},
                "decided_at": _TEXT,
            },
            required=("decision_type", "decided_by"),
            any_of=(
                {"required": ["run_id", "payload", "decided_at"]},
                {"required": ["projection_schema", "decision_payload"]},
            ),
        )
    if event_type == "worker_called":
        return _payload_schema(
            properties={
                "projection_schema": {"const": "harness-safe-summary/v1"},
                "run_id": _TEXT,
                "step_id": _TEXT,
                "worker_type": {
                    "enum": [
                        "llm",
                        "skill",
                        "skill_evolution",
                        "subagent",
                        "retrieval",
                        "memory",
                        "mcp",
                        "quality_gate",
                        "artifact",
                        "script",
                    ]
                },
                "activity_id": _TEXT,
                "idempotency_key": _TEXT,
                "activity_attempt": _POSITIVE_INTEGER,
                "activity_contract_version": _TEXT,
                "inputs": _OBJECT,
                "metadata": _OBJECT,
                "input_ref": _CHECKSUM_TEXT,
                "input_count": _NONNEGATIVE_INTEGER,
                "metadata_ref": _CHECKSUM_TEXT,
            },
            required=("worker_type",),
            any_of=(
                {"required": ["run_id", "step_id", "inputs", "metadata"]},
                {
                    "required": [
                        "projection_schema",
                        "activity_id",
                        "idempotency_key",
                        "activity_attempt",
                        "activity_contract_version",
                        "input_ref",
                        "input_count",
                        "metadata_ref",
                    ]
                },
            ),
        )
    if event_type == "worker_result_recorded":
        return _payload_schema(
            properties={
                "projection_schema": {"const": "harness-safe-summary/v1"},
                "status": {
                    "enum": ["succeeded", "failed", "blocked", "waiting_approval"]
                },
                "output": _OBJECT,
                "artifacts": _ARRAY_OF_TEXT,
                "diagnostics": _OBJECT,
                "metrics": _OBJECT,
                "error": _NULLABLE_TEXT,
                "output_ref": _CHECKSUM_TEXT,
                "diagnostics_ref": _CHECKSUM_TEXT,
                "metric_count": _NONNEGATIVE_INTEGER,
                "artifact_count": _NONNEGATIVE_INTEGER,
                "artifact_ref_checksums": _ARRAY_OF_CHECKSUMS,
                "error_ref": _CHECKSUM_TEXT,
            },
            required=("status",),
            any_of=(
                {"required": ["output", "artifacts", "diagnostics", "metrics"]},
                {
                    "required": [
                        "projection_schema",
                        "output_ref",
                        "diagnostics_ref",
                        "metric_count",
                        "artifact_count",
                        "artifact_ref_checksums",
                    ]
                },
            ),
        )
    if event_type == "gate_evaluated":
        return _payload_schema(
            properties={
                "projection_schema": {"const": "harness-safe-summary/v1"},
                "gate": {"type": "string", "minLength": 1, "maxLength": 128},
                "passed": _BOOLEAN,
                "reason": _NULLABLE_TEXT,
                "details": _OBJECT,
                "reason_ref": _CHECKSUM_TEXT,
                "details_ref": _CHECKSUM_TEXT,
            },
            required=("gate", "passed"),
            any_of=(
                {"required": ["details"]},
                {"required": ["projection_schema", "details_ref"]},
            ),
        )
    if event_type == "checkpoint_created":
        return _payload_schema(
            properties={
                "projection_schema": {"const": "harness-safe-summary/v1"},
                "checkpoint_id": _TEXT,
            },
            required=("checkpoint_id",),
        )
    raise EventSchemaError(f"Harness event schema is not defined: {event_type}")


def _workflow_sensitivity_policy(event_type: str) -> SensitivityPolicy:
    if event_type == "workflow_resumed":
        return SensitivityPolicy(
            field_rules={"/resume_metadata": FieldDisposition.SENSITIVE},
            redact_sensitive=True,
        )
    if event_type in {
        "edge_evaluated",
        "edge_traversed",
        "edge_rejected",
    }:
        return SensitivityPolicy(
            field_rules={
                "/condition": FieldDisposition.SENSITIVE,
                "/condition_expr": FieldDisposition.SENSITIVE,
            },
            redact_sensitive=True,
        )
    if event_type in {
        "human_review_decision_received",
        "human_review_approved",
        "human_review_rejected",
        "human_review_needs_changes",
    }:
        return SensitivityPolicy(
            field_rules={
                "/actor_id": FieldDisposition.SENSITIVE,
                "/approval_id": FieldDisposition.SENSITIVE,
            },
            redact_sensitive=True,
        )
    if event_type in {"workflow_blocked", "workflow_budget_exceeded", "workflow_failed"}:
        return SensitivityPolicy(
            field_rules={"/error": FieldDisposition.SENSITIVE},
            redact_sensitive=True,
        )
    if event_type in {"step_paused", "step_blocked", "step_failed"}:
        return SensitivityPolicy(
            field_rules={
                "/outcome/error_message": FieldDisposition.SENSITIVE,
                "/outcome/error_details": FieldDisposition.SENSITIVE,
            },
            redact_sensitive=True,
        )
    if event_type == "step_retry_scheduled":
        return SensitivityPolicy(
            field_rules={"/error_message": FieldDisposition.SENSITIVE},
            redact_sensitive=True,
        )
    if event_type == "policy_violation":
        return SensitivityPolicy(
            field_rules={
                "/message": FieldDisposition.SENSITIVE,
                "/metadata": FieldDisposition.SENSITIVE,
                "/resource_estimate/input_keys": FieldDisposition.SENSITIVE,
            },
            redact_sensitive=True,
        )
    if event_type == "runtime_safety_violation":
        return SensitivityPolicy(
            field_rules={
                "/message": FieldDisposition.SENSITIVE,
                "/metadata": FieldDisposition.SENSITIVE,
            },
            redact_sensitive=True,
        )
    if event_type == "runner_capability_violation":
        return SensitivityPolicy(
            field_rules={
                "/implementation": FieldDisposition.SENSITIVE,
                "/message": FieldDisposition.SENSITIVE,
            },
            redact_sensitive=True,
        )
    return SensitivityPolicy()


def _workflow_operation_sensitivity_policy() -> SensitivityPolicy:
    return SensitivityPolicy(
        field_rules={
            "/actor_id": FieldDisposition.SENSITIVE,
            "/reason": FieldDisposition.SENSITIVE,
            "/details": FieldDisposition.SENSITIVE,
        },
        whole_document_reference=WholeDocumentReferenceDisposition.SECURE_REQUIRED,
        redact_sensitive=True,
    )


def _harness_sensitivity_policy(event_type: str) -> SensitivityPolicy:
    if event_type == "phase_recorded":
        return SensitivityPolicy(
            field_rules={
                "/input_refs/*": FieldDisposition.REFERENCE_ONLY,
                "/output_refs/*": FieldDisposition.REFERENCE_ONLY,
                "/gate_results/*/details": FieldDisposition.SENSITIVE,
                "/gate_results/*/diagnostics": FieldDisposition.REFERENCE_ONLY,
                "/gate_results/*/reason": FieldDisposition.SENSITIVE,
            },
            whole_document_reference=(
                WholeDocumentReferenceDisposition.SECURE_REQUIRED
            ),
            redact_sensitive=True,
        )
    if event_type == "decision_recorded":
        return SensitivityPolicy(
            field_rules={
                "/payload": FieldDisposition.REFERENCE_ONLY,
                "/reason": FieldDisposition.SENSITIVE,
            },
            whole_document_reference=(
                WholeDocumentReferenceDisposition.SECURE_REQUIRED
            ),
            redact_sensitive=True,
        )
    if event_type == "worker_called":
        return SensitivityPolicy(
            field_rules={
                "/inputs": FieldDisposition.REFERENCE_ONLY,
                "/metadata": FieldDisposition.REFERENCE_ONLY,
            },
            whole_document_reference=(
                WholeDocumentReferenceDisposition.SECURE_REQUIRED
            ),
        )
    if event_type == "worker_result_recorded":
        return SensitivityPolicy(
            field_rules={
                "/output": FieldDisposition.REFERENCE_ONLY,
                "/artifacts/*": FieldDisposition.REFERENCE_ONLY,
                "/diagnostics": FieldDisposition.REFERENCE_ONLY,
                "/metrics": FieldDisposition.SENSITIVE,
                "/error": FieldDisposition.SENSITIVE,
            },
            whole_document_reference=(
                WholeDocumentReferenceDisposition.SECURE_REQUIRED
            ),
            redact_sensitive=True,
        )
    if event_type == "gate_evaluated":
        return SensitivityPolicy(
            field_rules={
                "/details": FieldDisposition.SENSITIVE,
                "/reason": FieldDisposition.SENSITIVE,
            },
            redact_sensitive=True,
        )
    if event_type == "step_state_changed":
        return SensitivityPolicy(
            field_rules={
                "/error": FieldDisposition.SENSITIVE,
                "/output_ref": FieldDisposition.REFERENCE_ONLY,
                "/metadata/worker_result": FieldDisposition.REFERENCE_ONLY,
            },
            whole_document_reference=(
                WholeDocumentReferenceDisposition.SECURE_REQUIRED
            ),
            redact_sensitive=True,
        )
    return SensitivityPolicy()


def _validation_error(
    registration: EventSchemaRegistration,
    error: ValidationError,
) -> EventSchemaValidationError:
    return EventSchemaValidationError(
        event_type=registration.event_type,
        data_schema=registration.data_schema,
        path=_json_path(error),
        rule=str(error.validator or "schema"),
    )


def _json_path(error: ValidationError) -> str:
    if not error.absolute_path:
        return "$"
    return "$" + "".join(
        f"[{part}]" if isinstance(part, int) else f".{part}"
        for part in error.absolute_path
    )


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("JSON value must be an object")
    if any(not isinstance(key, str) for key in value):
        raise TypeError("JSON object keys must be strings")
    frozen: dict[str, Any] = {}
    for key in sorted(value):
        item = value[key]
        frozen[key] = _freeze_value(item)
    return MappingProxyType(frozen)


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, list):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_value(item) for item in value)
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON number must be finite")
        return 0 if value == 0 else value
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _thaw_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _thaw_value(item) for key, item in value.items()}


def _thaw_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _thaw_mapping(value)
    if isinstance(value, tuple):
        return [_thaw_value(item) for item in value]
    return copy.deepcopy(value)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("optional schema text must be a string")
    text = value.strip()
    return text or None


def _parse_historical_time(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("occurred_at is empty")
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    else:
        raise TypeError("occurred_at must be a string or datetime")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("occurred_at must contain an explicit timezone")
    return parsed.astimezone(UTC)


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    text = value.strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


_SCHEMA_VERSION_PATTERN = re.compile(r"^(?P<prefix>.*(?:/|^))v(?P<version>[1-9][0-9]*)$")
_PURE_CALLABLE_FORBIDDEN_OPCODES = frozenset(
    {
        "BUILD_SET",
        "DELETE_DEREF",
        "DELETE_GLOBAL",
        "IMPORT_FROM",
        "IMPORT_NAME",
        "IMPORT_STAR",
        "LOAD_BUILD_CLASS",
        "MAKE_FUNCTION",
        "SET_ADD",
        "SET_UPDATE",
        "STORE_DEREF",
        "STORE_GLOBAL",
    }
)
_PURE_CALLABLE_ALLOWED_BUILTINS = frozenset(
    {
        "AssertionError",
        "TypeError",
        "ValueError",
        "abs",
        "all",
        "any",
        "bool",
        "dict",
        "float",
        "int",
        "isinstance",
        "len",
        "list",
        "max",
        "min",
        "range",
        "round",
        "sorted",
        "str",
        "sum",
        "tuple",
    }
)
_PURE_CALLABLE_ALLOWED_METHODS = frozenset(
    {
        "count",
        "endswith",
        "get",
        "index",
        "items",
        "join",
        "keys",
        "lower",
        "lstrip",
        "replace",
        "rsplit",
        "rstrip",
        "split",
        "startswith",
        "strip",
        "upper",
        "values",
    }
)
_PURE_CALLABLE_REFLECTION_CONSTANTS = frozenset(
    {
        "__builtins__",
        "__class__",
        "__closure__",
        "__code__",
        "__dict__",
        "__func__",
        "__getattribute__",
        "__globals__",
        "__mro__",
        "__subclasses__",
        "cr_frame",
        "f_builtins",
        "f_globals",
        "f_locals",
        "func_globals",
        "gi_frame",
        "mro",
    }
)


def _validate_adjacent_schema_versions(source: str, target: str) -> None:
    source_match = _SCHEMA_VERSION_PATTERN.fullmatch(source)
    target_match = _SCHEMA_VERSION_PATTERN.fullmatch(target)
    if source_match is None or target_match is None:
        raise EventSchemaError(
            "upcast schemas must end in an explicit adjacent /vN version"
        )
    if source_match.group("prefix") != target_match.group("prefix"):
        raise EventSchemaError("upcaster cannot change the data-schema namespace")
    source_version = int(source_match.group("version"))
    target_version = int(target_match.group("version"))
    if target_version != source_version + 1:
        raise EventSchemaError(
            f"event upcaster must target the adjacent version: {source} -> {target}"
        )


def _validate_upcaster_purity(
    upcaster: EventUpcaster | None,
    event_type: str,
    data_schema: str,
) -> None:
    _validate_pure_schema_callable(
        upcaster,
        role="upcaster",
        event_type=event_type,
        data_schema=data_schema,
    )


def _validate_custom_validator_purity(
    validator: PayloadValidator,
    event_type: str,
    data_schema: str,
) -> None:
    _validate_pure_schema_callable(
        validator,
        role="custom validator",
        event_type=event_type,
        data_schema=data_schema,
    )


def _validate_pure_schema_callable(
    function: Any,
    *,
    role: str,
    event_type: str,
    data_schema: str,
) -> None:
    if not isinstance(function, FunctionType):
        raise EventSchemaError(
            f"event {role} must be a plain function: {event_type} ({data_schema})"
        )
    if inspect.iscoroutinefunction(function) or inspect.isgeneratorfunction(function):
        raise EventSchemaError(
            f"event {role} must be synchronous: {event_type} ({data_schema})"
        )
    parameters = tuple(inspect.signature(function).parameters.values())
    if len(parameters) != 1 or any(
        parameter.kind
        not in {parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD}
        for parameter in parameters
    ):
        raise EventSchemaError(f"event {role} must accept exactly one payload argument")
    try:
        _audit_pure_schema_function(function)
    except EventSchemaError:
        raise
    except Exception as exc:
        raise EventSchemaError(
            f"event {role} purity could not be verified: {event_type} ({data_schema})"
        ) from exc


def _audit_pure_schema_function(function: FunctionType) -> None:
    closure = inspect.getclosurevars(function)
    for name in closure.builtins:
        if name not in _PURE_CALLABLE_ALLOWED_BUILTINS:
            raise EventSchemaError(f"event schema callable uses forbidden builtin: {name}")
    for name, value in {**closure.globals, **closure.nonlocals}.items():
        if isinstance(value, ModuleType) or not _is_pure_schema_constant(value):
            raise EventSchemaError(
                f"event schema callable captures forbidden dependency: {name}"
            )
    for value in function.__defaults__ or ():
        if not _is_pure_schema_constant(value):
            raise EventSchemaError("event schema callable has a mutable default")
    for value in (function.__kwdefaults__ or {}).values():
        if not _is_pure_schema_constant(value):
            raise EventSchemaError("event schema callable has a mutable default")
    _audit_pure_schema_code(function.__code__, function=function, seen=set())


def _audit_pure_schema_code(
    code: CodeType,
    *,
    function: FunctionType,
    seen: set[int],
) -> None:
    identity = id(code)
    if identity in seen:
        return
    seen.add(identity)
    for instruction in dis.get_instructions(code):
        operation = instruction.opname
        name = str(instruction.argval) if instruction.argval is not None else ""
        if operation in _PURE_CALLABLE_FORBIDDEN_OPCODES:
            raise EventSchemaError(
                f"event schema callable uses forbidden operation: {operation}"
            )
        if operation == "LOAD_ATTR":
            raise EventSchemaError(
                f"event schema callable uses forbidden attribute: {name}"
            )
        if operation == "LOAD_METHOD" and name not in _PURE_CALLABLE_ALLOWED_METHODS:
            raise EventSchemaError(
                f"event schema callable uses forbidden method: {name}"
            )
        if operation == "LOAD_GLOBAL" and name not in _PURE_CALLABLE_ALLOWED_BUILTINS:
            raise EventSchemaError(
                f"event schema callable uses forbidden global: {name}"
            )
        if operation == "LOAD_CONST":
            _audit_pure_schema_constant(instruction.argval, function=function, seen=seen)


def _audit_pure_schema_constant(
    value: Any,
    *,
    function: FunctionType,
    seen: set[int],
) -> None:
    if isinstance(value, CodeType):
        _audit_pure_schema_code(value, function=function, seen=seen)
        return
    if isinstance(value, str):
        if (
            value in _PURE_CALLABLE_REFLECTION_CONSTANTS
            or (value.startswith("__") and value.endswith("__"))
        ):
            raise EventSchemaError(
                f"event schema callable contains forbidden reflection constant: {value}"
            )
        return
    if value is None or isinstance(value, (bool, int, float, bytes)):
        return
    if isinstance(value, tuple):
        for item in value:
            _audit_pure_schema_constant(item, function=function, seen=seen)
        return
    raise EventSchemaError(
        f"event schema callable contains unsupported constant: {type(value).__name__}"
    )


def _is_pure_schema_constant(value: Any) -> bool:
    if value is None or isinstance(value, (bool, int, float, str, bytes)):
        return True
    if isinstance(value, tuple):
        return all(_is_pure_schema_constant(item) for item in value)
    return False


def _run_pure_upcaster(
    upcaster: EventUpcaster,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    produced = upcaster(_freeze_mapping(_thaw_mapping(_freeze_mapping(payload))))
    if not isinstance(produced, Mapping):
        raise TypeError("upcaster must return a mapping")
    return _thaw_mapping(_freeze_mapping(produced))


def _run_pure_validator(
    validator: PayloadValidator,
    payload: Mapping[str, Any],
) -> None:
    result = validator(_freeze_mapping(_thaw_mapping(_freeze_mapping(payload))))
    if result is not None:
        raise TypeError("custom validator must return None")
