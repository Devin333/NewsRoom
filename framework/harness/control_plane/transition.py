from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from framework.events.canonical import (
    StoredEvent,
    checksum_for,
    normalize_canonical_json,
    thaw_canonical_json,
)
from framework.events.errors import EventReplayMismatchError, EventStoreCorruptionError
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.state import (
    HarnessRunSpec,
    HarnessRunStatus,
    HarnessState,
    HarnessStepState,
    HarnessStepStatus,
)
from framework.harness.control_plane.transitions import RUN_TRANSITIONS, STEP_TRANSITIONS
from framework.shared.json import to_jsonable
from framework.shared.time import ensure_utc, format_datetime, parse_datetime


HARNESS_TRANSITION_DATA_SCHEMA = "newsroom.harness-transition/v1"
HARNESS_STATE_PROJECTION_SCHEMA = "newsroom.harness-state-projection/v1"
HARNESS_REDUCER_VERSION = "newsroom.harness-state-reducer/v1"
HARNESS_POLICY_VERSION = "newsroom.harness-control-policy/v1"
HARNESS_TRANSITION_EVENT_TYPE = "harness_transition_committed"
HARNESS_EVENT_SOURCE = "io.newsroom.harness.control-plane"


class HarnessTransitionKind(StrEnum):
    INITIALIZE = "initialize"
    RUN_START = "run_start"
    PLAN_ENTRY = "plan_entry"
    PLAN_EXIT = "plan_exit"
    EXECUTE_ENTRY = "execute_entry"
    EXECUTE_EXIT = "execute_exit"
    VERIFY_ENTRY = "verify_entry"
    VERIFY_EXIT = "verify_exit"
    REPLAN_ENTRY = "replan_entry"
    REPLAN_EXIT = "replan_exit"
    RETRY = "retry"
    ROUTE_TO_REPAIR = "route_to_repair"
    ROUTE_TO_STEP = "route_to_step"
    WAIT_FOR_APPROVAL = "wait_for_approval"
    APPROVAL_RESUME = "approval_resume"
    APPROVAL_CANCEL = "approval_cancel"
    WORKER_RESULT_COMMITTED = "worker_result_committed"
    STEP_SUCCESS = "step_success"
    BUDGET_EXHAUSTION = "budget_exhaustion"
    HALT = "halt"
    FAILURE = "failure"
    SUCCESS = "success"
    CANCEL = "cancel"
    WAIT = "wait"


_SAFE_STATE_INTEGER_KEYS = frozenset(
    {
        "evolution_epochs_used",
        "candidates_used",
        "patch_operations_used",
        "eval_cases_used",
        "sandbox_runs_used",
    }
)
_SAFE_STATE_TEXT_KEYS = frozenset({"repair_from_step_id"})
_SAFE_STEP_BOOLEAN_KEYS = frozenset({"approval_granted", "rerouted"})
_SAFE_STEP_INTEGER_KEYS = frozenset({"activity_attempt"})
_SAFE_STEP_TEXT_KEYS = frozenset(
    {
        "activity_id",
        "activity_type",
        "activity_contract_version",
        "activity_idempotency_key",
        "activity_input_checksum",
        "activity_identity_scope_ref",
        "activity_worker_version",
        "activity_result_event_id",
        "worker_result_ref",
        "worker_status",
    }
)
_REFERENCE_ONLY_STATE_KEYS = frozenset(
    {
        "outputs",
        "plan_keys",
        "claims",
        "questions",
        "terminal_reason",
    }
)
_REFERENCE_ONLY_STEP_KEYS = frozenset({"worker_result"})
_PROJECTED_STEP_METADATA_KEYS = frozenset(
    {"omitted_metadata_ref", "omitted_metadata_count"}
)
_PROJECTED_STATE_METADATA_KEYS = frozenset(
    {
        "outputs_ref",
        "outputs_count",
        "plan_keys_ref",
        "plan_keys_count",
        "claims_ref",
        "claims_count",
        "questions_ref",
        "questions_count",
        "terminal_reason_ref",
        "omitted_metadata_ref",
        "omitted_metadata_count",
    }
)


@dataclass(frozen=True, slots=True)
class HarnessStateProjection:
    run_id: str
    run_spec_checksum: str
    workflow_id: str
    workflow_checksum: str
    workflow_version: str
    status: str
    step_states: tuple[Mapping[str, Any], ...]
    current_step_id: str | None
    turn_count: int
    replan_count: int
    worker_call_count: int
    metadata: Mapping[str, Any]
    updated_at: datetime
    schema: str = HARNESS_STATE_PROJECTION_SCHEMA

    def __post_init__(self) -> None:
        for field_name in (
            "run_id",
            "run_spec_checksum",
            "workflow_id",
            "workflow_checksum",
            "workflow_version",
            "status",
            "schema",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise HarnessValidationError(f"{field_name} is required")
            object.__setattr__(self, field_name, value)
        if self.schema != HARNESS_STATE_PROJECTION_SCHEMA:
            raise HarnessValidationError("unsupported Harness state projection schema")
        HarnessRunStatus(self.status)
        for field_name in ("turn_count", "replan_count", "worker_call_count"):
            _nonnegative_int(getattr(self, field_name), field_name)
        if not isinstance(self.updated_at, datetime):
            raise HarnessValidationError("state projection updated_at must be a datetime")
        object.__setattr__(self, "updated_at", ensure_utc(self.updated_at))
        normalized_steps = normalize_canonical_json(
            [to_jsonable(value) for value in self.step_states],
            path="$.harness_transition.state.step_states",
        )
        normalized_metadata = normalize_canonical_json(
            to_jsonable(self.metadata),
            path="$.harness_transition.state.metadata",
        )
        if not isinstance(normalized_steps, tuple):
            raise HarnessValidationError("state projection step_states must be an array")
        if not isinstance(normalized_metadata, Mapping):
            raise HarnessValidationError("state projection metadata must be an object")
        object.__setattr__(self, "step_states", normalized_steps)
        object.__setattr__(self, "metadata", normalized_metadata)

    @classmethod
    def from_state(cls, state: HarnessState) -> HarnessStateProjection:
        if not isinstance(state, HarnessState):
            raise TypeError("state must be HarnessState")
        return cls(
            run_id=state.run_spec.run_id,
            run_spec_checksum=run_spec_checksum(state.run_spec),
            workflow_id=state.run_spec.workflow.workflow_id,
            workflow_checksum=workflow_checksum(state.run_spec),
            workflow_version=workflow_version(state.run_spec),
            status=state.status.value,
            step_states=tuple(_project_step_state(step) for step in state.step_states),
            current_step_id=state.current_step_id,
            turn_count=state.turn_count,
            replan_count=state.replan_count,
            worker_call_count=state.worker_call_count,
            metadata=_project_state_metadata(state.metadata),
            updated_at=state.updated_at,
        )

    @property
    def checksum(self) -> str:
        return checksum_for(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "run_id": self.run_id,
            "run_spec_checksum": self.run_spec_checksum,
            "workflow_id": self.workflow_id,
            "workflow_checksum": self.workflow_checksum,
            "workflow_version": self.workflow_version,
            "status": self.status,
            "step_states": thaw_canonical_json(self.step_states),
            "current_step_id": self.current_step_id,
            "turn_count": self.turn_count,
            "replan_count": self.replan_count,
            "worker_call_count": self.worker_call_count,
            "metadata": thaw_canonical_json(self.metadata),
            "updated_at": format_datetime(self.updated_at),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HarnessStateProjection:
        step_states = value.get("step_states")
        metadata = value.get("metadata")
        try:
            updated_at = parse_datetime(value.get("updated_at"))
        except (TypeError, ValueError, OverflowError) as exc:
            raise EventStoreCorruptionError(
                "Harness state projection updated_at is invalid"
            ) from exc
        if not isinstance(step_states, list | tuple):
            raise EventStoreCorruptionError("Harness state projection step_states is invalid")
        if not isinstance(metadata, Mapping):
            raise EventStoreCorruptionError("Harness state projection metadata is invalid")
        if updated_at is None:
            raise EventStoreCorruptionError("Harness state projection updated_at is invalid")
        try:
            return cls(
                schema=value.get("schema"),
                run_id=value.get("run_id"),
                run_spec_checksum=value.get("run_spec_checksum"),
                workflow_id=value.get("workflow_id"),
                workflow_checksum=value.get("workflow_checksum"),
                workflow_version=value.get("workflow_version"),
                status=value.get("status"),
                step_states=tuple(step_states),
                current_step_id=value.get("current_step_id"),
                turn_count=value.get("turn_count"),
                replan_count=value.get("replan_count"),
                worker_call_count=value.get("worker_call_count"),
                metadata=metadata,
                updated_at=updated_at,
            )
        except (HarnessValidationError, TypeError, ValueError) as exc:
            raise EventStoreCorruptionError("Harness state projection is invalid") from exc

    def restore(self, run_spec: HarnessRunSpec) -> HarnessState:
        _validate_run_spec(self, run_spec)
        declared = {step.step_id: step for step in run_spec.workflow.steps}
        restored_steps: list[HarnessStepState] = []
        for value in self.step_states:
            raw = thaw_canonical_json(value)
            if not isinstance(raw, dict):
                raise EventStoreCorruptionError("Harness projected step state is invalid")
            step_id = str(raw.get("step_id") or "")
            if step_id not in declared:
                raise EventReplayMismatchError(
                    sequence=0,
                    reason="projected step is not declared by the supplied workflow",
                    details={"step_id": step_id},
                )
            try:
                updated_at = parse_datetime(raw.get("updated_at"))
            except (TypeError, ValueError, OverflowError) as exc:
                raise EventStoreCorruptionError(
                    "Harness projected step updated_at is invalid"
                ) from exc
            metadata = raw.get("metadata")
            if updated_at is None or not isinstance(metadata, dict):
                raise EventStoreCorruptionError("Harness projected step state is incomplete")
            if raw.get("error_ref") is not None:
                metadata["error_ref"] = raw["error_ref"]
            restored_steps.append(
                HarnessStepState(
                    step_id=step_id,
                    status=raw.get("status"),
                    attempts=raw.get("attempts"),
                    replans=raw.get("replans"),
                    output_ref=(
                        declared[step_id].output_key
                        if raw.get("has_output_ref") is True
                        else None
                    ),
                    error=None,
                    metadata=metadata,
                    updated_at=updated_at,
                )
            )
        if tuple(step.step_id for step in restored_steps) != run_spec.workflow.step_ids:
            raise EventReplayMismatchError(
                sequence=0,
                reason="projected step order does not match the supplied workflow",
            )
        return HarnessState(
            run_spec=run_spec,
            status=self.status,
            step_states=tuple(restored_steps),
            current_step_id=self.current_step_id,
            turn_count=self.turn_count,
            replan_count=self.replan_count,
            worker_call_count=self.worker_call_count,
            metadata=thaw_canonical_json(self.metadata),
            updated_at=self.updated_at,
        )


@dataclass(frozen=True, slots=True)
class HarnessTransitionCommitted:
    run_id: str
    transition_kind: HarnessTransitionKind | str
    from_version: int
    state_version: int
    expected_last_sequence: int
    state: HarnessStateProjection
    before_state_checksum: str
    after_state_checksum: str
    occurred_at: datetime
    transition_id: str | None = None
    decision_ref: str | None = None
    gate_ref: str | None = None
    budget_ref: str | None = None
    activity_result_ref: str | None = None
    activity_result_event_id: str | None = None
    activity_id: str | None = None
    idempotency_key: str | None = None
    identity_scope_ref: str | None = field(default=None, repr=False)
    reducer_version: str = HARNESS_REDUCER_VERSION
    policy_version: str = HARNESS_POLICY_VERSION
    schema_version: str = HARNESS_TRANSITION_DATA_SCHEMA
    stream_sequence: int | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        run_id = str(self.run_id).strip()
        if not run_id:
            raise HarnessValidationError("transition run_id is required")
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "transition_kind", HarnessTransitionKind(self.transition_kind))
        _nonnegative_int(self.from_version, "from_version")
        _nonnegative_int(self.expected_last_sequence, "expected_last_sequence")
        if isinstance(self.state_version, bool) or not isinstance(self.state_version, int):
            raise HarnessValidationError("state_version must be an integer")
        if self.state_version != self.from_version + 1:
            raise HarnessValidationError("state_version must equal from_version + 1")
        if not isinstance(self.state, HarnessStateProjection):
            raise TypeError("state must be HarnessStateProjection")
        if self.state.run_id != run_id:
            raise HarnessValidationError("transition state run_id conflicts with transition")
        for field_name in (
            "before_state_checksum",
            "after_state_checksum",
            "reducer_version",
            "policy_version",
            "schema_version",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise HarnessValidationError(f"{field_name} is required")
            object.__setattr__(self, field_name, value)
        if not _is_checksum(self.before_state_checksum):
            raise HarnessValidationError(
                "before_state_checksum must be a sha256 reference"
            )
        if not _is_checksum(self.after_state_checksum):
            raise HarnessValidationError(
                "after_state_checksum must be a sha256 reference"
            )
        if self.schema_version != HARNESS_TRANSITION_DATA_SCHEMA:
            raise HarnessValidationError("unsupported Harness transition schema version")
        if not isinstance(self.occurred_at, datetime):
            raise HarnessValidationError("transition occurred_at must be a datetime")
        object.__setattr__(self, "occurred_at", ensure_utc(self.occurred_at))
        for field_name in (
            "decision_ref",
            "gate_ref",
            "budget_ref",
            "activity_result_ref",
        ):
            value = getattr(self, field_name)
            if value is not None and not _is_checksum(value):
                raise HarnessValidationError(f"{field_name} must be a sha256 reference")
        for field_name in (
            "activity_result_event_id",
            "activity_id",
            "idempotency_key",
        ):
            value = getattr(self, field_name)
            if value is not None:
                text = str(value).strip()
                if not text:
                    raise HarnessValidationError(f"{field_name} must not be blank")
                object.__setattr__(self, field_name, text)
        if self.identity_scope_ref is not None:
            identity_scope_ref = str(self.identity_scope_ref).strip()
            if not _is_checksum(identity_scope_ref):
                raise HarnessValidationError(
                    "identity_scope_ref must be a sha256 reference"
                )
            object.__setattr__(self, "identity_scope_ref", identity_scope_ref)
        if (self.activity_result_event_id is None) != (
            self.activity_result_ref is None
        ):
            raise HarnessValidationError(
                "activity result event id and checksum must be supplied together"
            )
        if (
            self.activity_result_event_id is not None
            and self.activity_result_ref
            != checksum_for(self.activity_result_event_id)
        ):
            raise HarnessValidationError(
                "activity_result_ref does not match activity_result_event_id"
            )
        if self.stream_sequence is not None:
            if isinstance(self.stream_sequence, bool) or not isinstance(self.stream_sequence, int):
                raise HarnessValidationError("stream_sequence must be an integer")
            if self.stream_sequence < 1:
                raise HarnessValidationError("stream_sequence must be positive")
        expected_transition_id = _transition_id(self)
        transition_id = self.transition_id or expected_transition_id
        if not str(transition_id).strip():
            raise HarnessValidationError("transition_id is required")
        if transition_id != expected_transition_id:
            raise HarnessValidationError(
                "transition_id does not match deterministic transition identity"
            )
        object.__setattr__(self, "transition_id", str(transition_id))

    @classmethod
    def create(
        cls,
        *,
        previous: HarnessState | None,
        state: HarnessState,
        from_version: int,
        expected_last_sequence: int,
        transition_kind: HarnessTransitionKind | str,
        occurred_at: datetime,
        decision: Any | None = None,
        gate_results: Any | None = None,
        budget: Any | None = None,
        activity_result_event_id: str | None = None,
        activity_id: str | None = None,
        idempotency_key: str | None = None,
        identity_scope_ref: str | None = None,
    ) -> HarnessTransitionCommitted:
        projection = HarnessStateProjection.from_state(state)
        if previous is None:
            before_checksum = initial_state_checksum(state.run_spec)
        else:
            if previous.run_spec.run_id != state.run_spec.run_id:
                raise HarnessValidationError("transition cannot cross Harness runs")
            before_checksum = HarnessStateProjection.from_state(previous).checksum
        transition = cls(
            run_id=state.run_spec.run_id,
            transition_kind=transition_kind,
            from_version=from_version,
            state_version=from_version + 1,
            expected_last_sequence=expected_last_sequence,
            state=projection,
            before_state_checksum=before_checksum,
            after_state_checksum=projection.checksum,
            occurred_at=occurred_at,
            decision_ref=_optional_ref(decision),
            gate_ref=_optional_ref(gate_results),
            budget_ref=_optional_ref(budget),
            activity_result_ref=_optional_ref(activity_result_event_id),
            activity_result_event_id=activity_result_event_id,
            activity_id=activity_id,
            idempotency_key=idempotency_key,
            identity_scope_ref=identity_scope_ref,
        )
        _validate_transition_semantics(previous, state, transition)
        return transition

    def to_payload(self) -> dict[str, Any]:
        state_payload = self.state.to_dict()
        # Canonical business_context owns run_id at the durable boundary.
        state_payload.pop("run_id", None)
        payload = {
            "transition_id": self.transition_id,
            "from_version": self.from_version,
            "state_version": self.state_version,
            "expected_last_sequence": self.expected_last_sequence,
            "transition_kind": self.transition_kind.value,
            "state": state_payload,
            "before_state_checksum": self.before_state_checksum,
            "after_state_checksum": self.after_state_checksum,
            "decision_ref": self.decision_ref,
            "gate_ref": self.gate_ref,
            "budget_ref": self.budget_ref,
            "activity_result_ref": self.activity_result_ref,
            "activity_result_event_id": self.activity_result_event_id,
            "activity_id": self.activity_id,
            "idempotency_key": self.idempotency_key,
            "workflow_version": self.state.workflow_version,
            "workflow_checksum": self.state.workflow_checksum,
            "reducer_version": self.reducer_version,
            "policy_version": self.policy_version,
            "schema_version": self.schema_version,
        }
        return {key: value for key, value in payload.items() if value is not None}

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        run_id: str,
        occurred_at: datetime,
        stream_sequence: int | None = None,
        identity_scope_ref: str | None = None,
    ) -> HarnessTransitionCommitted:
        state_value = payload.get("state")
        if not isinstance(state_value, Mapping):
            raise EventStoreCorruptionError("Harness transition state is missing")
        try:
            transition = cls(
                transition_id=payload.get("transition_id"),
                run_id=run_id,
                transition_kind=payload.get("transition_kind"),
                from_version=payload.get("from_version"),
                state_version=payload.get("state_version"),
                expected_last_sequence=payload.get("expected_last_sequence"),
                state=HarnessStateProjection.from_dict(
                    {**dict(state_value), "run_id": run_id}
                ),
                before_state_checksum=payload.get("before_state_checksum"),
                after_state_checksum=payload.get("after_state_checksum"),
                decision_ref=payload.get("decision_ref"),
                gate_ref=payload.get("gate_ref"),
                budget_ref=payload.get("budget_ref"),
                activity_result_ref=payload.get("activity_result_ref"),
                activity_result_event_id=payload.get("activity_result_event_id"),
                activity_id=payload.get("activity_id"),
                idempotency_key=payload.get("idempotency_key"),
                identity_scope_ref=identity_scope_ref,
                reducer_version=payload.get("reducer_version"),
                policy_version=payload.get("policy_version"),
                schema_version=payload.get("schema_version"),
                occurred_at=occurred_at,
                stream_sequence=stream_sequence,
            )
        except (HarnessValidationError, TypeError, ValueError) as exc:
            raise EventStoreCorruptionError("Harness transition payload is invalid") from exc
        if payload.get("workflow_version") != transition.state.workflow_version:
            raise EventStoreCorruptionError("Harness transition workflow version conflicts")
        if payload.get("workflow_checksum") != transition.state.workflow_checksum:
            raise EventStoreCorruptionError("Harness transition workflow checksum conflicts")
        return transition

    @classmethod
    def from_stored_event(cls, event: StoredEvent) -> HarnessTransitionCommitted:
        if not isinstance(event, StoredEvent):
            raise TypeError("event must be StoredEvent")
        event.verify_integrity()
        if event.source != HARNESS_EVENT_SOURCE:
            raise EventStoreCorruptionError(
                "stored Harness transition source is invalid"
            )
        if event.event_type != HARNESS_TRANSITION_EVENT_TYPE:
            raise EventStoreCorruptionError("stored event is not a Harness transition")
        if event.data_schema != HARNESS_TRANSITION_DATA_SCHEMA:
            raise EventStoreCorruptionError("stored Harness transition schema is incompatible")
        run_id = event.business_context.run_id
        if run_id is None or event.stream_id != f"run:{run_id}":
            raise EventStoreCorruptionError("stored Harness transition run context conflicts")
        if event.correlation_id != run_id:
            raise EventStoreCorruptionError(
                "stored Harness transition correlation context conflicts"
            )
        payload = thaw_canonical_json(event.payload or {})
        if not isinstance(payload, Mapping):
            raise EventStoreCorruptionError("stored Harness transition payload is invalid")
        scoped_ref = None if event.tenant_id is None else checksum_for(event.tenant_id)
        identity_scopes = (scoped_ref, None) if scoped_ref is not None else (None,)
        transition = None
        for identity_scope_ref in identity_scopes:
            try:
                candidate = cls.from_payload(
                    payload,
                    run_id=run_id,
                    occurred_at=event.occurred_at,
                    stream_sequence=event.stream_sequence,
                    identity_scope_ref=identity_scope_ref,
                )
            except EventStoreCorruptionError:
                continue
            if candidate.transition_id == event.event_id:
                transition = candidate
                break
        if transition is None:
            raise EventStoreCorruptionError(
                "Harness transition identity conflicts with event_id"
            )
        if transition.transition_id != event.event_id:
            raise EventStoreCorruptionError("Harness transition identity conflicts with event_id")
        if transition.expected_last_sequence != event.stream_sequence - 1:
            raise EventStoreCorruptionError(
                "Harness transition expected stream head conflicts with sequence"
            )
        expected_step_id = transition.state.current_step_id
        if (
            event.business_context.workflow_id != transition.state.workflow_id
            or event.business_context.step_id != expected_step_id
            or event.subject != (expected_step_id or run_id)
        ):
            raise EventStoreCorruptionError(
                "stored Harness transition workflow or step context conflicts"
            )
        _validate_stored_transition_shape(transition)
        return transition


@dataclass(frozen=True, slots=True)
class HarnessProjectedState:
    state: HarnessState | None
    state_version: int
    state_checksum: str
    last_transition_id: str | None = None
    last_transition_sequence: int | None = None


class HarnessStateProjector:
    """Pure reducer for ordered authoritative Harness transitions."""

    def project(
        self,
        run_spec: HarnessRunSpec,
        transitions: Iterable[HarnessTransitionCommitted],
    ) -> HarnessProjectedState:
        if not isinstance(run_spec, HarnessRunSpec):
            raise TypeError("run_spec must be HarnessRunSpec")
        state: HarnessState | None = None
        version = 0
        state_checksum = initial_state_checksum(run_spec)
        last_transition_id: str | None = None
        last_transition_sequence: int | None = None
        for transition in transitions:
            if not isinstance(transition, HarnessTransitionCommitted):
                raise TypeError("transitions must be HarnessTransitionCommitted values")
            sequence = transition.stream_sequence or transition.state_version
            if transition.run_id != run_spec.run_id:
                raise EventReplayMismatchError(
                    sequence=sequence,
                    reason="Harness transition belongs to another run",
                )
            if transition.reducer_version != HARNESS_REDUCER_VERSION:
                raise EventReplayMismatchError(
                    sequence=sequence,
                    reason="Harness reducer version is incompatible",
                )
            if transition.policy_version != HARNESS_POLICY_VERSION:
                raise EventReplayMismatchError(
                    sequence=sequence,
                    reason="Harness policy version is incompatible",
                )
            _validate_run_spec(transition.state, run_spec, sequence=sequence)
            if transition.from_version != version or transition.state_version != version + 1:
                raise EventReplayMismatchError(
                    sequence=sequence,
                    reason="Harness state version is not contiguous",
                    details={
                        "expected_from_version": version,
                        "actual_from_version": transition.from_version,
                        "actual_state_version": transition.state_version,
                    },
                )
            if transition.before_state_checksum != state_checksum:
                raise EventReplayMismatchError(
                    sequence=sequence,
                    reason="Harness transition before-state checksum mismatch",
                )
            if transition.after_state_checksum != transition.state.checksum:
                raise EventStoreCorruptionError(
                    "Harness transition after-state checksum mismatch"
                )
            if (
                last_transition_sequence is not None
                and transition.stream_sequence is not None
                and transition.stream_sequence <= last_transition_sequence
            ):
                raise EventReplayMismatchError(
                    sequence=transition.stream_sequence,
                    reason="Harness transitions are not ordered by stream sequence",
                )
            candidate_state = transition.state.restore(run_spec)
            try:
                _validate_transition_semantics(state, candidate_state, transition)
            except HarnessValidationError as exc:
                raise EventReplayMismatchError(
                    sequence=sequence,
                    reason="Harness transition violates control-plane semantics",
                    details={"transition_kind": transition.transition_kind.value},
                ) from exc
            state = candidate_state
            version = transition.state_version
            state_checksum = transition.after_state_checksum
            last_transition_id = transition.transition_id
            if transition.stream_sequence is not None:
                last_transition_sequence = transition.stream_sequence
        return HarnessProjectedState(
            state=state,
            state_version=version,
            state_checksum=state_checksum,
            last_transition_id=last_transition_id,
            last_transition_sequence=last_transition_sequence,
        )


def _validate_transition_semantics(
    previous: HarnessState | None,
    state: HarnessState,
    transition: HarnessTransitionCommitted,
) -> None:
    kind = transition.transition_kind
    if previous is None:
        if kind != HarnessTransitionKind.INITIALIZE:
            raise HarnessValidationError(
                "the first Harness transition must initialize the run"
            )
        expected = HarnessState.initial(state.run_spec)
        if (
            HarnessStateProjection.from_state(expected).checksum
            != HarnessStateProjection.from_state(state).checksum
        ):
            raise HarnessValidationError(
                "initialize transition must commit the exact initial Harness state"
            )
        return
    if kind == HarnessTransitionKind.INITIALIZE:
        raise HarnessValidationError("initialize transition cannot follow committed state")
    if run_spec_checksum(previous.run_spec) != run_spec_checksum(state.run_spec):
        raise HarnessValidationError("Harness transition cannot change the run specification")
    if tuple(step.step_id for step in previous.step_states) != tuple(
        step.step_id for step in state.step_states
    ):
        raise HarnessValidationError("Harness transition cannot change declared step order")

    if (
        state.status != previous.status
        and state.status not in RUN_TRANSITIONS[previous.status]
    ):
        raise HarnessValidationError("Harness transition contains an illegal run status change")
    route_reset = kind in {
        HarnessTransitionKind.ROUTE_TO_REPAIR,
        HarnessTransitionKind.ROUTE_TO_STEP,
    }
    previous_steps = {step.step_id: step for step in previous.step_states}
    for step in state.step_states:
        before = previous_steps[step.step_id]
        if step.status != before.status and not (
            step.status in STEP_TRANSITIONS[before.status]
            or (route_reset and step.status == HarnessStepStatus.PENDING)
        ):
            raise HarnessValidationError(
                "Harness transition contains an illegal step status change"
            )

    expected_turn_increment = int(
        kind
        in {
            HarnessTransitionKind.PLAN_ENTRY,
            HarnessTransitionKind.EXECUTE_ENTRY,
            HarnessTransitionKind.VERIFY_ENTRY,
        }
    )
    expected_replan_increment = int(kind == HarnessTransitionKind.REPLAN_ENTRY)
    expected_worker_increment = int(kind == HarnessTransitionKind.EXECUTE_ENTRY)
    if state.turn_count != previous.turn_count + expected_turn_increment:
        raise HarnessValidationError("Harness transition has an invalid turn increment")
    if state.replan_count != previous.replan_count + expected_replan_increment:
        raise HarnessValidationError("Harness transition has an invalid replan increment")
    if (
        state.worker_call_count
        != previous.worker_call_count + expected_worker_increment
    ):
        raise HarnessValidationError(
            "Harness transition has an invalid worker-call increment"
        )

    current_step_id = state.current_step_id
    for step in state.step_states:
        before = previous_steps[step.step_id]
        expected_attempt_increment = int(
            kind == HarnessTransitionKind.EXECUTE_ENTRY
            and step.step_id == current_step_id
        )
        expected_step_replan_increment = int(
            kind == HarnessTransitionKind.REPLAN_ENTRY
            and step.step_id == current_step_id
        )
        if step.attempts != before.attempts + expected_attempt_increment:
            raise HarnessValidationError(
                "Harness transition has an invalid activity-attempt increment"
            )
        if step.replans != before.replans + expected_step_replan_increment:
            raise HarnessValidationError(
                "Harness transition has an invalid step-replan increment"
            )

    current_step = (
        None
        if current_step_id is None
        else next(step for step in state.step_states if step.step_id == current_step_id)
    )
    if transition.activity_id is not None:
        _require_semantic(
            current_step is not None
            and current_step.metadata.get("activity_id") == transition.activity_id
            and current_step.metadata.get("activity_idempotency_key")
            == transition.idempotency_key
            and _activity_scope_matches(current_step, transition),
            kind,
        )
    if kind == HarnessTransitionKind.RUN_START:
        _require_semantic(state.status == HarnessRunStatus.RUNNING, kind)
    elif kind == HarnessTransitionKind.PLAN_ENTRY:
        _require_semantic(
            state.status == HarnessRunStatus.PLANNING
            and current_step is not None
            and current_step.status == HarnessStepStatus.PLANNING,
            kind,
        )
    elif kind == HarnessTransitionKind.PLAN_EXIT:
        _require_semantic(
            previous.status == HarnessRunStatus.PLANNING
            and state.status == HarnessRunStatus.PLANNING
            and current_step is not None
            and current_step.status
            in {HarnessStepStatus.PLANNING, HarnessStepStatus.PLAN_VERIFIED}
            and transition.gate_ref is not None,
            kind,
        )
    elif kind == HarnessTransitionKind.EXECUTE_ENTRY:
        _require_semantic(
            state.status == HarnessRunStatus.EXECUTING
            and current_step is not None
            and current_step.status == HarnessStepStatus.RUNNING
            and current_step.output_ref is None
            and current_step.error is None
            and current_step.metadata.get("activity_result_event_id") is None
            and current_step.metadata.get("worker_result_ref") is None
            and current_step.metadata.get("worker_status") is None
            and current_step.metadata.get("approval_granted") is None
            and transition.activity_id is not None
            and transition.idempotency_key is not None
            and transition.activity_result_event_id is None,
            kind,
        )
    elif kind == HarnessTransitionKind.WORKER_RESULT_COMMITTED:
        _require_activity_result_semantics(current_step, transition, kind)
    elif kind == HarnessTransitionKind.EXECUTE_EXIT:
        _require_activity_result_semantics(current_step, transition, kind)
        _require_semantic(
            _state_without_timestamps(previous) == _state_without_timestamps(state),
            kind,
        )
    elif kind == HarnessTransitionKind.VERIFY_ENTRY:
        _require_activity_result_semantics(current_step, transition, kind)
        _require_semantic(
            state.status == HarnessRunStatus.VERIFYING
            and current_step is not None
            and current_step.status == HarnessStepStatus.VERIFYING,
            kind,
        )
    elif kind == HarnessTransitionKind.VERIFY_EXIT:
        _require_activity_result_semantics(current_step, transition, kind)
        _require_semantic(
            transition.gate_ref is not None
            and _state_without_timestamps(previous) == _state_without_timestamps(state),
            kind,
        )
    elif kind == HarnessTransitionKind.STEP_SUCCESS:
        _require_activity_result_semantics(current_step, transition, kind)
        _require_semantic(
            state.status == HarnessRunStatus.RUNNING
            and current_step is not None
            and current_step.status == HarnessStepStatus.SUCCEEDED,
            kind,
        )
    elif kind == HarnessTransitionKind.RETRY:
        _require_semantic(
            state.status == HarnessRunStatus.EXECUTING
            and current_step is not None
            and current_step.status == HarnessStepStatus.RETRYING,
            kind,
        )
    elif kind == HarnessTransitionKind.REPLAN_ENTRY:
        _require_semantic(
            state.status == HarnessRunStatus.REPLANNING
            and current_step is not None
            and current_step.status == HarnessStepStatus.REPLANNING,
            kind,
        )
    elif kind == HarnessTransitionKind.REPLAN_EXIT:
        _require_semantic(
            _state_without_timestamps(previous) == _state_without_timestamps(state),
            kind,
        )
    elif kind == HarnessTransitionKind.WAIT_FOR_APPROVAL:
        _require_semantic(
            state.status == HarnessRunStatus.WAITING_APPROVAL
            and current_step is not None
            and current_step.status == HarnessStepStatus.WAITING_APPROVAL,
            kind,
        )
    elif kind == HarnessTransitionKind.APPROVAL_RESUME:
        _require_semantic(
            previous.status == HarnessRunStatus.WAITING_APPROVAL
            and state.status == HarnessRunStatus.RUNNING
            and current_step is not None
            and current_step.status == HarnessStepStatus.RUNNING
            and current_step.metadata.get("approval_granted") is True,
            kind,
        )
    elif kind == HarnessTransitionKind.APPROVAL_CANCEL:
        _require_semantic(
            previous.status == HarnessRunStatus.WAITING_APPROVAL
            and state.status == HarnessRunStatus.CANCELLED,
            kind,
        )
    elif kind in {
        HarnessTransitionKind.ROUTE_TO_REPAIR,
        HarnessTransitionKind.ROUTE_TO_STEP,
    }:
        _require_semantic(state.status == HarnessRunStatus.RUNNING, kind)
    elif kind == HarnessTransitionKind.SUCCESS:
        _require_semantic(state.status == HarnessRunStatus.SUCCEEDED, kind)
    elif kind == HarnessTransitionKind.FAILURE:
        _require_semantic(state.status == HarnessRunStatus.FAILED, kind)
    elif kind in {
        HarnessTransitionKind.HALT,
        HarnessTransitionKind.BUDGET_EXHAUSTION,
    }:
        _require_semantic(state.status == HarnessRunStatus.HALTED, kind)
    elif kind == HarnessTransitionKind.CANCEL:
        _require_semantic(state.status == HarnessRunStatus.CANCELLED, kind)
    elif kind == HarnessTransitionKind.WAIT:
        _require_semantic(state.status == HarnessRunStatus.BLOCKED, kind)


def _validate_stored_transition_shape(
    transition: HarnessTransitionCommitted,
) -> None:
    kind = transition.transition_kind
    state = transition.state
    current_step_status = _projected_current_step_status(state)
    valid = True
    if kind == HarnessTransitionKind.INITIALIZE:
        valid = (
            state.status == HarnessRunStatus.CREATED
            and state.turn_count == 0
            and state.replan_count == 0
            and state.worker_call_count == 0
            and all(
                value.get("status") == HarnessStepStatus.PENDING
                for value in state.step_states
            )
        )
    elif kind == HarnessTransitionKind.RUN_START:
        valid = state.status == HarnessRunStatus.RUNNING
    elif kind == HarnessTransitionKind.PLAN_ENTRY:
        valid = (
            state.status == HarnessRunStatus.PLANNING
            and current_step_status == HarnessStepStatus.PLANNING
        )
    elif kind == HarnessTransitionKind.PLAN_EXIT:
        valid = (
            state.status == HarnessRunStatus.PLANNING
            and current_step_status
            in {HarnessStepStatus.PLANNING, HarnessStepStatus.PLAN_VERIFIED}
            and transition.gate_ref is not None
        )
    elif kind == HarnessTransitionKind.EXECUTE_ENTRY:
        valid = (
            state.status == HarnessRunStatus.EXECUTING
            and current_step_status == HarnessStepStatus.RUNNING
            and transition.activity_id is not None
            and transition.idempotency_key is not None
            and transition.activity_result_event_id is None
        )
    elif kind in {
        HarnessTransitionKind.WORKER_RESULT_COMMITTED,
        HarnessTransitionKind.EXECUTE_EXIT,
    }:
        valid = (
            state.status == HarnessRunStatus.EXECUTING
            and current_step_status == HarnessStepStatus.RUNNING
            and transition.activity_result_event_id is not None
        )
    elif kind in {
        HarnessTransitionKind.VERIFY_ENTRY,
        HarnessTransitionKind.VERIFY_EXIT,
    }:
        valid = (
            state.status == HarnessRunStatus.VERIFYING
            and current_step_status == HarnessStepStatus.VERIFYING
            and transition.activity_result_event_id is not None
            and (
                kind != HarnessTransitionKind.VERIFY_EXIT
                or transition.gate_ref is not None
            )
        )
    elif kind == HarnessTransitionKind.STEP_SUCCESS:
        valid = (
            state.status == HarnessRunStatus.RUNNING
            and current_step_status == HarnessStepStatus.SUCCEEDED
            and transition.activity_result_event_id is not None
        )
    elif kind == HarnessTransitionKind.RETRY:
        valid = (
            state.status == HarnessRunStatus.EXECUTING
            and current_step_status == HarnessStepStatus.RETRYING
        )
    elif kind == HarnessTransitionKind.REPLAN_ENTRY:
        valid = (
            state.status == HarnessRunStatus.REPLANNING
            and current_step_status == HarnessStepStatus.REPLANNING
        )
    elif kind == HarnessTransitionKind.REPLAN_EXIT:
        valid = state.status == HarnessRunStatus.REPLANNING
    elif kind == HarnessTransitionKind.WAIT_FOR_APPROVAL:
        valid = (
            state.status == HarnessRunStatus.WAITING_APPROVAL
            and current_step_status == HarnessStepStatus.WAITING_APPROVAL
        )
    elif kind == HarnessTransitionKind.APPROVAL_RESUME:
        valid = (
            state.status == HarnessRunStatus.RUNNING
            and current_step_status == HarnessStepStatus.RUNNING
        )
    elif kind == HarnessTransitionKind.APPROVAL_CANCEL:
        valid = state.status == HarnessRunStatus.CANCELLED
    elif kind in {
        HarnessTransitionKind.ROUTE_TO_REPAIR,
        HarnessTransitionKind.ROUTE_TO_STEP,
    }:
        valid = state.status == HarnessRunStatus.RUNNING
    elif kind == HarnessTransitionKind.SUCCESS:
        valid = state.status == HarnessRunStatus.SUCCEEDED
    elif kind == HarnessTransitionKind.FAILURE:
        valid = state.status == HarnessRunStatus.FAILED
    elif kind in {
        HarnessTransitionKind.HALT,
        HarnessTransitionKind.BUDGET_EXHAUSTION,
    }:
        valid = state.status == HarnessRunStatus.HALTED
    elif kind == HarnessTransitionKind.CANCEL:
        valid = state.status == HarnessRunStatus.CANCELLED
    elif kind == HarnessTransitionKind.WAIT:
        valid = state.status == HarnessRunStatus.BLOCKED
    if not valid:
        raise EventStoreCorruptionError(
            "stored Harness transition violates control-plane semantics"
        )


def _projected_current_step_status(
    state: HarnessStateProjection,
) -> HarnessStepStatus | None:
    if state.current_step_id is None:
        return None
    for value in state.step_states:
        if value.get("step_id") == state.current_step_id:
            try:
                return HarnessStepStatus(value.get("status"))
            except (TypeError, ValueError) as exc:
                raise EventStoreCorruptionError(
                    "stored Harness transition step status is invalid"
                ) from exc
    raise EventStoreCorruptionError(
        "stored Harness transition current step is missing"
    )


def _require_activity_result_semantics(
    current_step: HarnessStepState | None,
    transition: HarnessTransitionCommitted,
    kind: HarnessTransitionKind,
) -> None:
    _require_semantic(
        current_step is not None
        and transition.activity_id is not None
        and transition.idempotency_key is not None
        and transition.activity_result_event_id is not None
        and current_step.metadata.get("activity_id") == transition.activity_id
        and current_step.metadata.get("activity_idempotency_key")
        == transition.idempotency_key
        and _activity_scope_matches(current_step, transition)
        and current_step.metadata.get("activity_result_event_id")
        == transition.activity_result_event_id,
        kind,
    )


def _require_semantic(condition: bool, kind: HarnessTransitionKind) -> None:
    if not condition:
        raise HarnessValidationError(
            f"Harness {kind.value} transition contains an invalid state delta"
        )


def _activity_scope_matches(
    current_step: HarnessStepState,
    transition: HarnessTransitionCommitted,
) -> bool:
    activity_scope_ref = current_step.metadata.get("activity_identity_scope_ref")
    if activity_scope_ref == transition.identity_scope_ref:
        return True
    activity_id = str(current_step.metadata.get("activity_id") or "")
    return (
        activity_scope_ref is None
        and activity_id.startswith("harness-activity:")
    )


def _state_without_timestamps(state: HarnessState) -> dict[str, Any]:
    value = state.to_dict()
    value.pop("updated_at", None)
    for step in value.get("step_states", ()):
        if isinstance(step, dict):
            step.pop("updated_at", None)
    return value


def initial_state_checksum(run_spec: HarnessRunSpec) -> str:
    return checksum_for(
        {
            "schema": HARNESS_STATE_PROJECTION_SCHEMA,
            "run_id": run_spec.run_id,
            "run_spec_checksum": run_spec_checksum(run_spec),
            "state_version": 0,
            "state": None,
        }
    )


def run_spec_checksum(run_spec: HarnessRunSpec) -> str:
    return checksum_for(run_spec.to_dict())


def workflow_checksum(run_spec: HarnessRunSpec) -> str:
    return checksum_for(run_spec.workflow.to_dict())


def workflow_version(run_spec: HarnessRunSpec) -> str:
    value = run_spec.workflow.metadata.get("version", "1")
    text = str(value).strip()
    if not text:
        raise HarnessValidationError("workflow version must not be blank")
    return text


def _project_step_state(step: HarnessStepState) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    omitted: dict[str, Any] = {}
    for key, value in step.metadata.items():
        if key in _SAFE_STEP_BOOLEAN_KEYS and isinstance(value, bool):
            metadata[key] = value
        elif key in _SAFE_STEP_INTEGER_KEYS:
            metadata[key] = _nonnegative_int(value, f"step metadata {key}")
        elif key in _SAFE_STEP_TEXT_KEYS and value is not None:
            text = str(value).strip()
            if text:
                metadata[key] = text
        elif key in _REFERENCE_ONLY_STEP_KEYS:
            metadata[f"{key}_ref"] = checksum_for(to_jsonable(value))
        elif key in _PROJECTED_STEP_METADATA_KEYS:
            metadata[key] = value
        elif key == "error_ref":
            continue
        else:
            omitted[str(key)] = value
    if omitted:
        metadata["omitted_metadata_ref"] = checksum_for(to_jsonable(omitted))
        metadata["omitted_metadata_count"] = len(omitted)
    payload = {
        "step_id": step.step_id,
        "status": step.status.value,
        "attempts": step.attempts,
        "replans": step.replans,
        "has_output_ref": step.output_ref is not None,
        "metadata": metadata,
        "updated_at": format_datetime(step.updated_at),
    }
    if step.output_ref is not None:
        payload["output_ref_checksum"] = checksum_for(step.output_ref)
    if step.error is not None:
        payload["error_ref"] = checksum_for(step.error)
    elif step.metadata.get("error_ref") is not None:
        payload["error_ref"] = step.metadata["error_ref"]
    return payload


def _project_state_metadata(value: Mapping[str, Any]) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    omitted: dict[str, Any] = {}
    for key, item in value.items():
        if key in _SAFE_STATE_INTEGER_KEYS:
            projected[key] = _nonnegative_int(item, f"state metadata {key}")
        elif key in _SAFE_STATE_TEXT_KEYS and item is not None:
            text = str(item).strip()
            if text:
                projected[key] = text
        elif key in _REFERENCE_ONLY_STATE_KEYS:
            projected[f"{key}_ref"] = checksum_for(to_jsonable(item))
            if isinstance(item, Mapping | list | tuple | set | frozenset):
                projected[f"{key}_count"] = len(item)
        elif key in _PROJECTED_STATE_METADATA_KEYS:
            projected[key] = item
        else:
            omitted[str(key)] = item
    if omitted:
        projected["omitted_metadata_ref"] = checksum_for(to_jsonable(omitted))
        projected["omitted_metadata_count"] = len(omitted)
    return projected


def _validate_run_spec(
    projection: HarnessStateProjection,
    run_spec: HarnessRunSpec,
    *,
    sequence: int = 0,
) -> None:
    if projection.run_id != run_spec.run_id:
        raise EventReplayMismatchError(sequence=sequence, reason="Harness run_id mismatch")
    if projection.run_spec_checksum != run_spec_checksum(run_spec):
        raise EventReplayMismatchError(
            sequence=sequence,
            reason="Harness run specification checksum mismatch",
        )
    if projection.workflow_id != run_spec.workflow.workflow_id:
        raise EventReplayMismatchError(
            sequence=sequence,
            reason="Harness workflow id mismatch",
        )
    if projection.workflow_checksum != workflow_checksum(run_spec):
        raise EventReplayMismatchError(
            sequence=sequence,
            reason="Harness workflow checksum mismatch",
        )
    if projection.workflow_version != workflow_version(run_spec):
        raise EventReplayMismatchError(
            sequence=sequence,
            reason="Harness workflow version mismatch",
        )


def _transition_id(transition: HarnessTransitionCommitted) -> str:
    identity = _transition_identity(transition)
    digest = hashlib.sha256(checksum_for(identity).encode("utf-8")).hexdigest()
    prefix = (
        "harness-transition-v2"
        if transition.identity_scope_ref is not None
        else "harness-transition"
    )
    return f"{prefix}:{digest}"


def legacy_transition_id(transition: HarnessTransitionCommitted) -> str:
    identity = _transition_identity(transition, include_identity_scope=False)
    digest = hashlib.sha256(checksum_for(identity).encode("utf-8")).hexdigest()
    return f"harness-transition:{digest}"


def _transition_identity(
    transition: HarnessTransitionCommitted,
    *,
    include_identity_scope: bool = True,
) -> dict[str, Any]:
    identity = {
        "run_id": transition.run_id,
        "from_version": transition.from_version,
        "state_version": transition.state_version,
        "transition_kind": transition.transition_kind.value,
        "activity_id": transition.activity_id,
        "idempotency_key": transition.idempotency_key,
        "schema_version": transition.schema_version,
    }
    if include_identity_scope and transition.identity_scope_ref is not None:
        identity["identity_scope_ref"] = transition.identity_scope_ref
    return identity


def _optional_ref(value: Any | None) -> str | None:
    return None if value is None else checksum_for(to_jsonable(value))


def _is_checksum(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    digest = value.removeprefix("sha256:")
    return len(digest) == 64 and all(character in "0123456789abcdef" for character in digest)


def _nonnegative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HarnessValidationError(f"{field_name} must be an integer")
    if value < 0:
        raise HarnessValidationError(f"{field_name} must not be negative")
    return value


__all__ = [
    "HARNESS_POLICY_VERSION",
    "HARNESS_EVENT_SOURCE",
    "HARNESS_REDUCER_VERSION",
    "HARNESS_STATE_PROJECTION_SCHEMA",
    "HARNESS_TRANSITION_DATA_SCHEMA",
    "HARNESS_TRANSITION_EVENT_TYPE",
    "HarnessProjectedState",
    "HarnessStateProjection",
    "HarnessStateProjector",
    "HarnessTransitionCommitted",
    "HarnessTransitionKind",
    "initial_state_checksum",
    "legacy_transition_id",
    "run_spec_checksum",
    "workflow_checksum",
    "workflow_version",
]
