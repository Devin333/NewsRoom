from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from framework.artifacts.paths import validate_artifact_path_segment
from framework.events.canonical import (
    BusinessContext,
    ProducerIdentity,
    PayloadReference,
    StoredEvent,
    checksum_for,
    thaw_canonical_json,
)
from framework.events.errors import (
    EventIncompleteHistoryError,
    EventIntegrityError,
    EventReplayMismatchError,
    EventStoreCorruptionError,
)
from framework.events.ports import EventReaderPort, EventRuntimePort
from framework.events.runtime.models import StreamReadRequest
from framework.events.runtime.activities import (
    REPLAY_ACTIVITY_RECORD_SCHEMA,
    ActivityRecorder,
    ActivityRecordingHandle,
    RecordedActivityResolver,
    RecordedActivityStorePort,
    RecordedActivityWrite,
    ReplayActivityCorruptionError,
    ReplayActivityDescriptor,
    ReplayActivityIncompleteError,
    ReplayActivityMissingError,
    ReplayActivityRegistry,
    ReplayActivityOutcome,
    ReplayActivityStatus,
    ReplayActivityVersionError,
    ResolvedReplayActivity,
)
from framework.events.runtime.history import (
    DETERMINISTIC_HISTORY_EXTENSION,
    DeterministicHistoryRecord,
)
from framework.events.runtime.publisher import EventPublishRequest
from framework.events.schema.security import SecurityClassification
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.event import HarnessEvent
from framework.harness.control_plane.event_log import (
    HarnessEventLogEntry,
    event_log_entry_from_stored_event,
)
from framework.harness.control_plane.replay_history import (
    harness_activity_kind,
    harness_activity_history,
    harness_event_history,
    harness_transition_history,
)
from framework.harness.control_plane.activity import (
    HARNESS_ACTIVITY_CONTRACT,
    HARNESS_ACTIVITY_EXTENSION,
    HarnessActivity,
    harness_activity_input_checksum,
    validate_activity_call_marker,
)
from framework.harness.control_plane.state import (
    HarnessRunSpec,
    HarnessState,
    HarnessStepState,
)
from framework.harness.control_plane.transition import (
    HARNESS_EVENT_SOURCE,
    HARNESS_TRANSITION_DATA_SCHEMA,
    HARNESS_TRANSITION_EVENT_TYPE,
    HarnessStateProjection,
    HarnessStateProjector,
    HarnessTransitionCommitted,
    HarnessTransitionKind,
    legacy_transition_id,
)
from framework.harness.quality.verdict import gate_result_evidence
from framework.harness.workers.result import HarnessWorkerResult, HarnessWorkerStatus
from framework.shared.time import format_datetime, parse_datetime


HARNESS_DATA_SCHEMA = "newsroom.harness-event/v1"
HARNESS_SAFE_PROJECTION = "harness-safe-summary/v1"
_LEGACY_TRACE_ID_PATTERN = re.compile(
    r"(?:[0-9a-fA-F]{16}|[0-9a-fA-F]{32}|"
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\Z"
)
_HARNESS_STATUS_VALUES = frozenset(
    {
        "blocked",
        "cancelled",
        "created",
        "executing",
        "failed",
        "halted",
        "pending",
        "plan_verified",
        "planning",
        "replanning",
        "retrying",
        "running",
        "skipped",
        "succeeded",
        "verifying",
        "waiting_approval",
    }
)
_HARNESS_TRANSITION_KINDS = frozenset(
    {
        "approval_cancel",
        "approval_resume",
        "budget_exhaustion",
        "cancel",
        "execute_entry",
        "failure",
        "halt",
        "plan_entry",
        "plan_exit",
        "replan",
        "retry",
        "retry_execute_entry",
        "route_to_repair",
        "route_to_step",
        "run_start",
        "step_success",
        "success",
        "verify_complete",
        "verify_entry",
        "wait",
        "wait_for_approval",
    }
)


@dataclass(frozen=True, slots=True)
class HarnessTransitionCommit:
    state: HarnessState
    transition: HarnessTransitionCommitted
    stored_event: StoredEvent | None


@dataclass(frozen=True, slots=True)
class HarnessRecovery:
    state: HarnessState | None
    state_version: int
    expected_last_sequence: int
    transitions: tuple[HarnessTransitionCommitted, ...]
    stored_events: tuple[StoredEvent, ...]
    worker_results: Mapping[str, HarnessWorkerResult]
    called_activity_ids: frozenset[str] = frozenset()

    @property
    def current_worker_result(self) -> HarnessWorkerResult | None:
        if self.state is None or self.state.current_step_id is None:
            return None
        return self.worker_results.get(self.state.current_step_id)


@dataclass(frozen=True, slots=True)
class _ResolvedHarnessActivity:
    activity: ResolvedReplayActivity
    worker_result: HarnessWorkerResult


@dataclass(frozen=True, slots=True)
class HarnessEventCanonicalAdapter:
    """Maps typed Harness facts to and from the canonical durable boundary."""

    producer: ProducerIdentity = ProducerIdentity(
        component="framework.harness.control_plane",
        version="1",
    )
    tenant_id: str | None = None
    security_classification: SecurityClassification | str = SecurityClassification.INTERNAL
    activity_security_classification: SecurityClassification | str = (
        SecurityClassification.CONFIDENTIAL
    )

    def __post_init__(self) -> None:
        tenant_id = self.tenant_id
        if tenant_id is not None:
            tenant_id = str(tenant_id).strip()
            if not tenant_id:
                raise HarnessValidationError("tenant_id must not be blank")
        object.__setattr__(self, "tenant_id", tenant_id)
        object.__setattr__(
            self,
            "security_classification",
            SecurityClassification(self.security_classification),
        )
        object.__setattr__(
            self,
            "activity_security_classification",
            SecurityClassification(self.activity_security_classification),
        )

    @property
    def identity_scope_ref(self) -> str | None:
        return None if self.tenant_id is None else checksum_for(self.tenant_id)

    def to_publish_request(self, event: HarnessEvent) -> EventPublishRequest:
        if not isinstance(event, HarnessEvent):
            raise TypeError("event must be HarnessEvent")
        run_id = validate_artifact_path_segment(event.run_id, field="run_id")
        _validate_payload_context(
            event.payload,
            run_id=run_id,
            step_id=event.step_id,
            event_type=event.event_type.value,
            occurred_at=event.occurred_at,
        )
        canonical_payload = _canonical_harness_payload(event)
        harness_extension: dict[str, Any] = {
            "metadata": _harness_metadata_projection(event.metadata)
        }
        if event.trace_id is not None:
            # A legacy trace id without a span id is correlation data only and
            # must never be injected as canonical W3C trace context.
            harness_extension["legacy_trace_id"] = _legacy_trace_id(event.trace_id)
        history = harness_event_history(
            event,
            data_schema=HARNESS_DATA_SCHEMA,
        )
        if event.deterministic_history is not None:
            history = DeterministicHistoryRecord.from_dict(
                event.deterministic_history
            )
        return EventPublishRequest(
            event_id=_scoped_harness_event_id(
                str(event.event_id),
                identity_scope_ref=self.identity_scope_ref,
            ),
            event_type=event.event_type.value,
            data_schema=HARNESS_DATA_SCHEMA,
            source=HARNESS_EVENT_SOURCE,
            subject=event.step_id or run_id,
            occurred_at=event.occurred_at,
            stream_id=f"run:{run_id}",
            correlation_id=run_id,
            business_context=BusinessContext(
                run_id=run_id,
                workflow_id=_optional_metadata_text(event.metadata, "workflow_id"),
                step_id=event.step_id,
            ),
            producer=self.producer,
            tenant_id=self.tenant_id,
            security_classification=self.security_classification,
            payload=canonical_payload,
            extensions={
                "harness": harness_extension,
                DETERMINISTIC_HISTORY_EXTENSION: history.to_dict(),
            },
        )

    def to_transition_publish_request(
        self,
        transition: HarnessTransitionCommitted,
    ) -> EventPublishRequest:
        if not isinstance(transition, HarnessTransitionCommitted):
            raise TypeError("transition must be HarnessTransitionCommitted")
        if transition.identity_scope_ref != self.identity_scope_ref:
            raise HarnessValidationError(
                "Harness transition identity scope conflicts with adapter tenant"
            )
        run_id = validate_artifact_path_segment(transition.run_id, field="run_id")
        return EventPublishRequest(
            event_id=str(transition.transition_id),
            event_type=HARNESS_TRANSITION_EVENT_TYPE,
            data_schema=HARNESS_TRANSITION_DATA_SCHEMA,
            source=HARNESS_EVENT_SOURCE,
            subject=transition.state.current_step_id or run_id,
            occurred_at=transition.occurred_at,
            stream_id=f"run:{run_id}",
            correlation_id=run_id,
            business_context=BusinessContext(
                run_id=run_id,
                workflow_id=transition.state.workflow_id,
                step_id=transition.state.current_step_id,
            ),
            producer=self.producer,
            tenant_id=self.tenant_id,
            security_classification=self.security_classification,
            payload=transition.to_payload(),
            extensions={
                DETERMINISTIC_HISTORY_EXTENSION: harness_transition_history(
                    transition
                ).to_dict()
            },
        )

    def to_activity_result_publish_request(
        self,
        activity: HarnessActivity,
        recorded: RecordedActivityWrite,
    ) -> EventPublishRequest:
        if not isinstance(activity, HarnessActivity):
            raise TypeError("activity must be HarnessActivity")
        if not isinstance(recorded, RecordedActivityWrite):
            raise TypeError("recorded must be RecordedActivityWrite")
        recorded.verify_integrity()
        if self.tenant_id is None:
            raise HarnessValidationError(
                "Harness activity history requires an authoritative tenant"
            )
        if activity.identity_scope_ref != self.identity_scope_ref:
            raise HarnessValidationError(
                "Harness activity identity scope conflicts with adapter tenant"
            )
        run_id = validate_artifact_path_segment(activity.run_id, field="run_id")
        descriptor = recorded.record.activity
        outcome = recorded.record.outcome
        _validate_harness_activity_descriptor(descriptor, activity)
        if (
            descriptor.tenant_id != self.tenant_id
            or descriptor.security_classification
            is not self.activity_security_classification
        ):
            raise EventStoreCorruptionError(
                "Harness activity record security scope conflicts with adapter"
            )
        if outcome.status is ReplayActivityStatus.PENDING:
            raise HarnessValidationError("Harness activity event requires a terminal record")
        completed_at = outcome.completed_at
        if completed_at is None:  # pragma: no cover - terminal outcome invariant
            raise HarnessValidationError("Harness activity completion time is missing")
        worker_status = _worker_status_from_outcome(outcome)
        return EventPublishRequest(
            event_id=activity.result_event_id,
            event_type="worker_result_recorded",
            data_schema=HARNESS_DATA_SCHEMA,
            source=HARNESS_EVENT_SOURCE,
            subject=activity.step_id,
            occurred_at=completed_at,
            stream_id=f"run:{run_id}",
            correlation_id=run_id,
            business_context=BusinessContext(
                run_id=run_id,
                step_id=activity.step_id,
            ),
            producer=self.producer,
            tenant_id=self.tenant_id,
            security_classification=self.activity_security_classification,
            content_type=recorded.recorded_ref.content_type,
            payload_ref=recorded.recorded_ref,
            extensions={
                HARNESS_ACTIVITY_EXTENSION: {
                    "schema": recorded.record.schema,
                    "activity": activity.to_dict(),
                    "status": worker_status,
                    "input_ref": descriptor.input_ref.to_dict(),
                    "output_ref": (
                        None
                        if outcome.output_ref is None
                        else outcome.output_ref.to_dict()
                    ),
                    "error_ref": (
                        None
                        if outcome.error_ref is None
                        else outcome.error_ref.to_dict()
                    ),
                    "error_class": outcome.error_class,
                    "accepted_at": format_datetime(descriptor.accepted_at),
                    "started_at": format_datetime(outcome.started_at),
                    "completed_at": format_datetime(completed_at),
                },
                DETERMINISTIC_HISTORY_EXTENSION: harness_activity_history(recorded).to_dict(),
            },
        )

    def from_stored_event(self, event: StoredEvent) -> HarnessEvent:
        _validate_stored_harness_event(event)
        if event.event_type == HARNESS_TRANSITION_EVENT_TYPE:
            transition = HarnessTransitionCommitted.from_stored_event(event)
            return HarnessEvent(
                event_id=event.event_id,
                event_type=event.event_type,
                run_id=transition.run_id,
                step_id=event.business_context.step_id,
                payload=transition.to_payload(),
                occurred_at=event.occurred_at,
                deterministic_history=_stored_deterministic_history(event),
            )
        if event.payload_ref is not None:
            extension = thaw_canonical_json(
                event.extensions.get(HARNESS_ACTIVITY_EXTENSION, {})
            )
            if not isinstance(extension, dict):
                raise HarnessValidationError(
                    "stored Harness activity extension must be an object"
                )
            return HarnessEvent(
                event_id=event.event_id,
                event_type=event.event_type,
                run_id=event.business_context.run_id or "",
                step_id=event.business_context.step_id,
                payload={
                    "projection_schema": HARNESS_SAFE_PROJECTION,
                    "status": extension.get("status"),
                    "output_ref": event.payload_ref.expected_checksum,
                    "activity_id": _activity_extension_id(extension),
                },
                occurred_at=event.occurred_at,
                deterministic_history=_stored_deterministic_history(event),
            )
        payload = thaw_canonical_json(event.payload or {})
        if not isinstance(payload, dict):
            raise HarnessValidationError("stored Harness payload must be an object")
        run_id = event.business_context.run_id
        if run_id is None:
            raise HarnessValidationError("stored Harness event requires business_context.run_id")
        step_id = event.business_context.step_id
        _validate_payload_context(
            payload,
            run_id=run_id,
            step_id=step_id,
            event_type=event.event_type,
            occurred_at=event.occurred_at,
        )
        extension = thaw_canonical_json(event.extensions.get("harness", {}))
        if not isinstance(extension, dict):
            raise HarnessValidationError("stored Harness extension must be an object")
        metadata = extension.get("metadata", {})
        if not isinstance(metadata, dict):
            raise HarnessValidationError("stored Harness metadata must be an object")
        legacy_trace_id = extension.get("legacy_trace_id")
        return HarnessEvent(
            event_id=event.event_id,
            event_type=event.event_type,
            run_id=run_id,
            step_id=step_id,
            payload=payload,
            metadata=metadata,
            occurred_at=event.occurred_at,
            trace_id=str(legacy_trace_id) if legacy_trace_id is not None else None,
            deterministic_history=_stored_deterministic_history(event),
        )


class DurableHarnessEventPort:
    """Harness sink whose projection advances only after canonical commit."""

    def __init__(
        self,
        runtime: EventRuntimePort,
        *,
        reader: EventReaderPort | None = None,
        activity_store: RecordedActivityStorePort | None = None,
        secure_activity_store: RecordedActivityStorePort | None = None,
        adapter: HarnessEventCanonicalAdapter | None = None,
        projector: HarnessStateProjector | None = None,
    ) -> None:
        if runtime is None:
            raise HarnessValidationError("event runtime is required")
        self._runtime = runtime
        self._reader = reader
        if (
            activity_store is not None
            and secure_activity_store is not None
            and activity_store is not secure_activity_store
        ):
            raise HarnessValidationError(
                "activity_store and secure_activity_store must identify one store"
            )
        self._activity_store = activity_store or secure_activity_store
        self._activity_recorder = (
            None
            if self._activity_store is None
            else ActivityRecorder(self._activity_store)
        )
        self._activity_handles: dict[str, ActivityRecordingHandle] = {}
        self._adapter = adapter or HarnessEventCanonicalAdapter()
        self._projector = projector or HarnessStateProjector()
        self.events: list[HarnessEvent] = []
        self.event_log_entries: list[HarnessEventLogEntry] = []

    def create_activity(
        self,
        *,
        run_id: str,
        step_id: str,
        attempt: int,
        activity_type: str,
        inputs: Mapping[str, Any],
        contract_version: str = HARNESS_ACTIVITY_CONTRACT,
        worker_version: str = "1",
    ) -> HarnessActivity:
        self.require_activity_storage()
        return HarnessActivity.for_worker_call(
            run_id=run_id,
            step_id=step_id,
            attempt=attempt,
            activity_type=activity_type,
            inputs=inputs,
            identity_scope_ref=self._adapter.identity_scope_ref,
            contract_version=contract_version,
            worker_version=worker_version,
        )

    def record(self, event: HarnessEvent) -> HarnessEvent:
        request = self._adapter.to_publish_request(event)
        stored = self._runtime.publish(request)
        _validate_commit_result(stored, request)
        projected = self._adapter.from_stored_event(stored)
        log_entry = event_log_entry_from_stored_event(stored)
        # These are compatibility/read projections. They intentionally advance
        # only after EventRuntime.publish() returned a committed StoredEvent.
        self.events.append(projected)
        self.event_log_entries.append(log_entry)
        return projected

    def entries_for_run(self, run_id: str) -> tuple[HarnessEventLogEntry, ...]:
        if self._reader is not None:
            return tuple(
                event_log_entry_from_stored_event(event)
                for event in self._read_stored_history(run_id)
            )
        return tuple(entry for entry in self.event_log_entries if entry.run_id == run_id)

    def require_activity_storage(self) -> None:
        if self._activity_store is None:
            raise EventIncompleteHistoryError(
                "durable Harness worker execution requires a recorded activity store"
            )
        if self._adapter.tenant_id is None:
            raise EventIncompleteHistoryError(
                "durable Harness worker execution requires an authoritative tenant"
            )

    def accept_activity(
        self,
        activity: HarnessActivity,
        inputs: Mapping[str, Any],
        *,
        accepted_at: datetime,
        started_at: datetime,
    ) -> HarnessWorkerResult | None:
        if not isinstance(activity, HarnessActivity):
            raise TypeError("activity must be HarnessActivity")
        if not isinstance(inputs, Mapping):
            raise TypeError("inputs must be a mapping")
        self.require_activity_storage()
        assert self._activity_recorder is not None
        assert self._adapter.tenant_id is not None
        if harness_activity_input_checksum(inputs) != activity.input_checksum:
            raise EventReplayMismatchError(
                sequence=activity.attempt,
                reason="Harness accepted activity input conflicts with descriptor",
            )
        handle = self._activity_recorder.accept(
            activity_id=activity.activity_id,
            activity_kind=harness_activity_kind(activity.activity_type),
            input_value=inputs,
            idempotency_key=activity.idempotency_key,
            attempt=activity.attempt,
            contract_version=activity.contract_version,
            handler_version=activity.worker_version,
            accepted_at=accepted_at,
            started_at=started_at,
            context={
                "run_id": activity.run_id,
                "step_id": activity.step_id,
                "activity_type": activity.activity_type,
                "identity_scope_ref": activity.identity_scope_ref,
            },
            tenant_id=self._adapter.tenant_id,
            security_classification=self._adapter.activity_security_classification,
        )
        if handle.activity.input_checksum != activity.input_checksum:
            raise EventStoreCorruptionError(
                "recorded Harness activity input checksum conflicts with descriptor"
            )
        self._activity_handles[activity.activity_id] = handle
        if not handle.is_terminal:
            return None
        resolved = self._resolve_recorded_activity(
            handle.activity,
            handle.recorded_ref,
        )
        return resolved.worker_result

    def resolve_replay_activity(
        self,
        state: HarnessState,
    ) -> tuple[ReplayActivityDescriptor, PayloadReference] | None:
        if not isinstance(state, HarnessState):
            raise TypeError("state must be HarnessState")
        step_id = state.current_step_id
        if step_id is None:
            return None
        step = next(
            item for item in state.step_states if item.step_id == step_id
        )
        result_event_id = step.metadata.get("activity_result_event_id")
        if result_event_id is None:
            return None
        activity = _activity_from_step_metadata(state.run_spec, step)
        if activity is None:
            raise EventStoreCorruptionError(
                "Harness activity result reference has no activity descriptor"
            )
        reader = self._require_reader()
        event = reader.get_event(
            str(result_event_id),
            tenant_id=self._adapter.tenant_id,
        )
        if event is None:
            raise EventIncompleteHistoryError(
                "Harness decision is missing its committed activity result"
            )
        resolved = self._resolve_activity_event(event, expected=activity)
        if event.payload_ref is None:  # pragma: no cover - resolver validates this
            raise EventStoreCorruptionError(
                "Harness activity result event is missing its secure reference"
            )
        if self._adapter.tenant_id is None:  # pragma: no cover - resolver validates this
            raise EventStoreCorruptionError(
                "Harness activity result event is missing tenant scope"
            )
        descriptor = resolved.activity.activity
        try:
            history_value = thaw_canonical_json(
                event.extensions.get(DETERMINISTIC_HISTORY_EXTENSION)
            )
            if not isinstance(history_value, Mapping):
                raise TypeError("activity history must be an object")
            history = DeterministicHistoryRecord.from_dict(history_value)
            history.verify_integrity()
        except (TypeError, ValueError) as exc:
            raise EventStoreCorruptionError(
                "committed Harness activity history is corrupt"
            ) from exc
        if (
            history.policy.expected_activity != descriptor
            or history.policy.recorded_activity_ref != event.payload_ref
        ):
            raise EventStoreCorruptionError(
                "committed Harness activity history conflicts with secure result"
            )
        return history.policy.expected_activity, history.policy.recorded_activity_ref

    def record_activity_result(
        self,
        activity: HarnessActivity,
        result: HarnessWorkerResult,
        *,
        completed_at: datetime,
    ) -> HarnessEvent:
        if not isinstance(activity, HarnessActivity):
            raise TypeError("activity must be HarnessActivity")
        if not isinstance(result, HarnessWorkerResult):
            raise TypeError("result must be HarnessWorkerResult")
        reader = self._require_reader()
        existing = reader.get_event(
            activity.result_event_id,
            tenant_id=self._adapter.tenant_id,
        )
        if existing is not None:
            recovered = self._resolve_activity_event(existing, expected=activity)
            if recovered.worker_result.to_dict() != result.to_dict():
                raise EventReplayMismatchError(
                    sequence=existing.stream_sequence,
                    reason="Harness activity retry produced a different result",
                )
            projected = self._adapter.from_stored_event(existing)
            self._append_compatibility_projection(existing, projected)
            return projected

        self.require_activity_storage()
        handle = self._activity_handles.get(activity.activity_id)
        if handle is None:
            raise EventIncompleteHistoryError(
                "Harness activity result has no accepted durable activity"
            )
        if result.status.value == "succeeded":
            recorded = handle.succeed(result.to_dict(), completed_at=completed_at)
        else:
            recorded = handle.fail(
                f"harness_worker_{result.status.value}",
                result.to_dict(),
                completed_at=completed_at,
            )
        request = self._adapter.to_activity_result_publish_request(activity, recorded)
        stored = self._runtime.publish(request)
        _validate_commit_result(stored, request)
        self._resolve_activity_event(stored, expected=activity)
        projected = self._adapter.from_stored_event(stored)
        self._append_compatibility_projection(stored, projected)
        return projected

    def _append_compatibility_projection(
        self,
        stored: StoredEvent,
        projected: HarnessEvent,
    ) -> None:
        if not any(event.event_id == projected.event_id for event in self.events):
            self.events.append(projected)
        if not any(
            entry.event_id == stored.event_id for entry in self.event_log_entries
        ):
            self.event_log_entries.append(event_log_entry_from_stored_event(stored))

    def commit_transition(
        self,
        previous: HarnessState | None,
        state: HarnessState,
        *,
        from_version: int,
        transition_kind: HarnessTransitionKind | str,
        occurred_at: datetime,
        decision: Any | None = None,
        gate_results: Any | None = None,
        budget: Any | None = None,
        activity: HarnessActivity | None = None,
        activity_result_event_id: str | None = None,
    ) -> HarnessTransitionCommit:
        if not isinstance(state, HarnessState):
            raise TypeError("state must be HarnessState")
        reader = self._require_reader()
        stream_id = f"run:{validate_artifact_path_segment(state.run_spec.run_id, field='run_id')}"
        head = reader.get_stream_high_watermark(
            stream_id,
            tenant_id=self._adapter.tenant_id,
        ) or 0
        transition = HarnessTransitionCommitted.create(
            previous=previous,
            state=state,
            from_version=from_version,
            expected_last_sequence=head,
            transition_kind=transition_kind,
            occurred_at=occurred_at,
            decision=decision,
            gate_results=gate_results,
            budget=budget,
            activity_result_event_id=activity_result_event_id,
            activity_id=None if activity is None else activity.activity_id,
            idempotency_key=None if activity is None else activity.idempotency_key,
            identity_scope_ref=self._adapter.identity_scope_ref,
        )
        existing = reader.get_event(
            str(transition.transition_id),
            tenant_id=self._adapter.tenant_id,
        )
        legacy_existing = None
        legacy_id = legacy_transition_id(transition)
        if legacy_id != transition.transition_id:
            legacy_existing = reader.get_event(
                legacy_id,
                tenant_id=self._adapter.tenant_id,
            )
        if existing is not None and legacy_existing is not None:
            raise EventStoreCorruptionError(
                "scoped and legacy Harness transitions both exist"
            )
        if existing is not None or legacy_existing is not None:
            stored_existing = existing or legacy_existing
            assert stored_existing is not None
            committed = HarnessTransitionCommitted.from_stored_event(stored_existing)
            if legacy_existing is not None:
                _validate_legacy_transition_retry(committed, transition)
            else:
                _validate_transition_retry(committed, transition)
            return HarnessTransitionCommit(
                state=state,
                transition=committed,
                stored_event=stored_existing,
            )

        history = self._read_stored_history(
            state.run_spec.run_id,
            through_sequence=head,
        )
        committed_transitions = tuple(
            HarnessTransitionCommitted.from_stored_event(event)
            for event in history
            if event.event_type == HARNESS_TRANSITION_EVENT_TYPE
        )
        current = self._projector.project(state.run_spec, committed_transitions)
        if current.state_version != from_version:
            raise EventReplayMismatchError(
                sequence=head,
                reason="Harness transition attempted from a stale state version",
                details={
                    "expected_from_version": current.state_version,
                    "actual_from_version": from_version,
                },
            )
        if previous is None:
            if current.state is not None:
                raise EventReplayMismatchError(
                    sequence=head,
                    reason="Harness initialization attempted after state already exists",
                )
        elif current.state_checksum != HarnessStateProjection.from_state(
            previous
        ).checksum:
            raise EventReplayMismatchError(
                sequence=head,
                reason="Harness in-memory projection does not match durable state",
            )

        request = self._adapter.to_transition_publish_request(transition)
        stored = self._runtime.publish(
            request,
            expected_last_sequence=head,
        )
        _validate_commit_result(stored, request)
        committed = HarnessTransitionCommitted.from_stored_event(stored)
        _validate_transition_retry(committed, transition)
        projected = self._adapter.from_stored_event(stored)
        self.events.append(projected)
        self.event_log_entries.append(event_log_entry_from_stored_event(stored))
        return HarnessTransitionCommit(
            state=state,
            transition=committed,
            stored_event=stored,
        )

    def recover(self, run_spec: HarnessRunSpec) -> HarnessRecovery:
        if not isinstance(run_spec, HarnessRunSpec):
            raise TypeError("run_spec must be HarnessRunSpec")
        reader = self._require_reader()
        stream_id = f"run:{validate_artifact_path_segment(run_spec.run_id, field='run_id')}"
        high_watermark = reader.get_stream_high_watermark(
            stream_id,
            tenant_id=self._adapter.tenant_id,
        ) or 0
        stored_events = self._read_stored_history(
            run_spec.run_id,
            through_sequence=high_watermark,
        )
        transitions = tuple(
            HarnessTransitionCommitted.from_stored_event(event)
            for event in stored_events
            if event.event_type == HARNESS_TRANSITION_EVENT_TYPE
        )
        projected = self._projector.project(run_spec, transitions)
        state, worker_results = self._hydrate_activity_results(
            projected.state,
            stored_events,
            transitions,
            expected_state_checksum=projected.state_checksum,
        )
        return HarnessRecovery(
            state=state,
            state_version=projected.state_version,
            expected_last_sequence=high_watermark,
            transitions=transitions,
            stored_events=stored_events,
            worker_results=worker_results,
            called_activity_ids=_called_activity_ids_for_recovery(
                state=state,
                transitions=transitions,
                stored_events=stored_events,
                tenant_id=self._adapter.tenant_id,
                classification=self._adapter.security_classification,
            ),
        )

    def read_history(self, run_id: str) -> tuple[HarnessEvent, ...]:
        stored = self._read_stored_history(run_id)
        return tuple(self._adapter.from_stored_event(event) for event in stored)

    def _read_stored_history(
        self,
        run_id: str,
        *,
        through_sequence: int | None = None,
    ) -> tuple[StoredEvent, ...]:
        reader = self._require_reader()
        safe_run_id = validate_artifact_path_segment(run_id, field="run_id")
        stream_id = f"run:{safe_run_id}"
        high_watermark = through_sequence
        if high_watermark is None:
            high_watermark = reader.get_stream_high_watermark(
                stream_id,
                tenant_id=self._adapter.tenant_id,
            ) or 0
        if high_watermark == 0:
            return ()
        cursor = None
        events: list[StoredEvent] = []
        while True:
            page = reader.read_stream(
                StreamReadRequest(
                    stream_id=stream_id,
                    cursor=cursor,
                    limit=500,
                    through_sequence=high_watermark,
                    tenant_id=self._adapter.tenant_id,
                    data_schemas=frozenset(
                        {HARNESS_DATA_SCHEMA, HARNESS_TRANSITION_DATA_SCHEMA}
                    ),
                )
            )
            events.extend(page.events)
            if page.next_cursor is None:
                break
            cursor = page.next_cursor
        return tuple(events)

    def _hydrate_activity_results(
        self,
        state: HarnessState | None,
        stored_events: tuple[StoredEvent, ...],
        transitions: tuple[HarnessTransitionCommitted, ...],
        *,
        expected_state_checksum: str,
    ) -> tuple[HarnessState | None, Mapping[str, HarnessWorkerResult]]:
        if state is None:
            return None, {}
        by_id = {event.event_id: event for event in stored_events}
        resolved_records: dict[str, _ResolvedHarnessActivity] = {}

        def resolve_record(
            event_id: str,
            activity: HarnessActivity,
        ) -> _ResolvedHarnessActivity:
            event = by_id.get(event_id)
            if event is None:
                raise EventIncompleteHistoryError(
                    "Harness history is missing a committed worker activity result"
                )
            record = resolved_records.get(event_id)
            if record is None:
                record = self._resolve_activity_event(event, expected=activity)
                resolved_records[event_id] = record
            else:
                _validate_harness_activity_descriptor(
                    record.activity.activity,
                    activity,
                )
            return record

        worker_results: dict[str, HarnessWorkerResult] = {}
        hydrated_steps: list[HarnessStepState] = []
        for step in state.step_states:
            activity = _activity_from_step_metadata(state.run_spec, step)
            if activity is None:
                hydrated_steps.append(step)
                continue
            committed_event_id = step.metadata.get("activity_result_event_id")
            event_id = str(committed_event_id or activity.result_event_id)
            if event_id not in by_id:
                if committed_event_id is not None:
                    raise EventIncompleteHistoryError(
                        "Harness history is missing a committed worker activity result"
                    )
                hydrated_steps.append(step)
                continue
            record = resolve_record(event_id, activity)
            worker_result = record.worker_result
            worker_results[step.step_id] = worker_result
            if committed_event_id is None:
                hydrated_steps.append(step)
                continue
            worker_result_ref = checksum_for(worker_result.to_dict())
            if step.metadata.get("worker_result_ref") != worker_result_ref:
                raise EventStoreCorruptionError(
                    "Harness projected worker result checksum conflicts with activity result"
                )
            hydrated_steps.append(
                replace(
                    step,
                    metadata={
                        **step.metadata,
                        "worker_result": worker_result.to_dict(),
                    },
                )
            )

        outputs: dict[str, Any] = {}
        plan_keys: set[str] = set()
        claims: set[str] = set()
        questions: set[str] = set()
        for transition in transitions:
            if transition.transition_kind != HarnessTransitionKind.STEP_SUCCESS:
                continue
            transition_state = transition.state.restore(state.run_spec)
            step_id = transition_state.current_step_id
            if step_id is None or transition.activity_result_event_id is None:
                raise EventStoreCorruptionError(
                    "Harness step success is missing its activity result reference"
                )
            step = next(
                item for item in transition_state.step_states if item.step_id == step_id
            )
            activity = _activity_from_step_metadata(state.run_spec, step)
            if activity is None:
                raise EventStoreCorruptionError(
                    "Harness step success is missing its activity descriptor"
                )
            result = resolve_record(
                transition.activity_result_event_id,
                activity,
            ).worker_result
            step_spec = next(
                item
                for item in state.run_spec.workflow.steps
                if item.step_id == step_id
            )
            if step_spec.output_key:
                outputs[step_spec.output_key] = result.output
            if "plan_key" in result.output:
                plan_keys.add(str(result.output["plan_key"]))
            claims.update(_coerce_output_sequence(result.output.get("claims")))
            questions.update(_coerce_output_sequence(result.output.get("questions")))

        metadata = dict(state.metadata)
        recovered_values: dict[str, Any] = {
            "outputs": outputs,
            "plan_keys": tuple(sorted(plan_keys)),
            "claims": tuple(sorted(claims)),
            "questions": tuple(sorted(questions)),
        }
        for key, value in recovered_values.items():
            if f"{key}_ref" in metadata:
                metadata[key] = value
        hydrated = replace(
            state,
            step_states=tuple(hydrated_steps),
            metadata=metadata,
        )
        if HarnessStateProjection.from_state(hydrated).checksum != expected_state_checksum:
            raise EventStoreCorruptionError(
                "hydrated Harness state conflicts with the durable state projection"
            )
        return hydrated, worker_results

    def _resolve_activity_event(
        self,
        event: StoredEvent,
        *,
        expected: HarnessActivity,
    ) -> _ResolvedHarnessActivity:
        self.require_activity_storage()
        assert self._activity_store is not None
        assert self._adapter.tenant_id is not None
        event.verify_integrity()
        if (
            event.event_id != expected.result_event_id
            or event.event_type != "worker_result_recorded"
            or event.data_schema != HARNESS_DATA_SCHEMA
            or event.source != HARNESS_EVENT_SOURCE
            or event.stream_id != f"run:{expected.run_id}"
            or event.business_context.run_id != expected.run_id
            or event.business_context.step_id != expected.step_id
            or event.tenant_id != self._adapter.tenant_id
            or event.security_classification
            is not self._adapter.activity_security_classification
            or event.payload_ref is None
            or event.content_type != event.payload_ref.content_type
        ):
            raise EventStoreCorruptionError(
                "committed Harness activity event identity is invalid"
            )
        extension = thaw_canonical_json(
            event.extensions.get(HARNESS_ACTIVITY_EXTENSION, {})
        )
        if not isinstance(extension, Mapping):
            raise EventStoreCorruptionError(
                "committed Harness activity extension is invalid"
            )
        activity_value = extension.get("activity")
        if not isinstance(activity_value, Mapping):
            raise EventStoreCorruptionError(
                "committed Harness activity descriptor is missing"
            )
        stored_activity = HarnessActivity.from_dict(activity_value)
        if stored_activity != expected:
            raise EventStoreCorruptionError(
                "committed Harness activity descriptor conflicts with state"
            )
        try:
            history_value = thaw_canonical_json(
                event.extensions.get(DETERMINISTIC_HISTORY_EXTENSION)
            )
            if not isinstance(history_value, Mapping):
                raise TypeError("activity history must be an object")
            history = DeterministicHistoryRecord.from_dict(history_value)
            history.verify_integrity()
        except (TypeError, ValueError) as exc:
            raise EventStoreCorruptionError(
                "committed Harness activity history is corrupt"
            ) from exc
        descriptor = history.policy.expected_activity
        recorded_ref = history.policy.recorded_activity_ref
        if descriptor is None or recorded_ref is None or recorded_ref != event.payload_ref:
            raise EventStoreCorruptionError(
                "committed Harness activity history is missing its recorded binding"
            )
        _validate_harness_activity_descriptor(descriptor, expected)
        if (
            descriptor.tenant_id != self._adapter.tenant_id
            or descriptor.security_classification
            is not self._adapter.activity_security_classification
        ):
            raise EventStoreCorruptionError(
                "committed Harness activity descriptor has an invalid security scope"
            )
        resolved = self._resolve_recorded_activity(descriptor, recorded_ref)
        if resolved.activity.activity != descriptor:
            raise EventStoreCorruptionError(
                "committed Harness activity descriptor conflicts with recorded history"
            )
        _validate_harness_activity_extension(
            extension,
            expected=expected,
            resolved=resolved.activity,
            occurred_at=event.occurred_at,
        )
        return resolved

    def _resolve_recorded_activity(
        self,
        descriptor: ReplayActivityDescriptor,
        recorded_ref: PayloadReference,
    ) -> _ResolvedHarnessActivity:
        assert self._activity_store is not None
        registry = ReplayActivityRegistry()
        registry.register(descriptor.pinned_version)
        try:
            resolved = RecordedActivityResolver(
                self._activity_store,
                registry,
            ).resolve(descriptor, recorded_ref)
            worker_result = _worker_result_from_recorded_activity(
                self._activity_store,
                resolved,
            )
        except ReplayActivityMissingError as exc:
            raise EventIncompleteHistoryError(
                "committed Harness activity result is unavailable"
            ) from exc
        except ReplayActivityIncompleteError as exc:
            raise EventIncompleteHistoryError(
                "committed Harness activity result is incomplete"
            ) from exc
        except (ReplayActivityCorruptionError, ReplayActivityVersionError) as exc:
            raise EventStoreCorruptionError(
                "committed Harness activity result is corrupt"
            ) from exc
        return _ResolvedHarnessActivity(resolved, worker_result)

    def _require_reader(self) -> EventReaderPort:
        if self._reader is None:
            raise HarnessValidationError(
                "durable Harness transition reader is required; memory-only recovery is forbidden"
            )
        return self._reader


class DurableHarnessTransitionPort(DurableHarnessEventPort):
    def __init__(
        self,
        runtime: EventRuntimePort,
        reader: EventReaderPort,
        *,
        activity_store: RecordedActivityStorePort | None = None,
        secure_activity_store: RecordedActivityStorePort | None = None,
        adapter: HarnessEventCanonicalAdapter | None = None,
        projector: HarnessStateProjector | None = None,
    ) -> None:
        super().__init__(
            runtime,
            reader=reader,
            activity_store=activity_store,
            secure_activity_store=secure_activity_store,
            adapter=adapter,
            projector=projector,
        )


def _validate_commit_result(stored: StoredEvent, request: EventPublishRequest) -> None:
    if not isinstance(stored, StoredEvent):
        raise HarnessValidationError("event runtime must return StoredEvent after commit")
    stored.verify_integrity()
    if stored.event_id != request.event_id:
        raise HarnessValidationError("event runtime returned a different Harness event_id")
    if stored.event_type != request.event_type or stored.data_schema != request.data_schema:
        raise HarnessValidationError("event runtime returned a different Harness schema identity")
    if stored.stream_id != request.stream_id:
        raise HarnessValidationError("event runtime returned a different Harness stream")


def _validate_stored_harness_event(event: StoredEvent) -> None:
    if not isinstance(event, StoredEvent):
        raise TypeError("event must be StoredEvent")
    event.verify_integrity()
    expected_schema = (
        HARNESS_TRANSITION_DATA_SCHEMA
        if event.event_type == HARNESS_TRANSITION_EVENT_TYPE
        else HARNESS_DATA_SCHEMA
    )
    if event.data_schema != expected_schema:
        raise HarnessValidationError("stored event is not a Harness event schema")
    if event.source != HARNESS_EVENT_SOURCE:
        raise HarnessValidationError("stored Harness event has an unexpected producer source")


def _validate_payload_context(
    payload: Mapping[str, Any],
    *,
    run_id: str,
    step_id: str | None,
    event_type: str,
    occurred_at: Any,
) -> None:
    payload_run_id = payload.get("run_id")
    if payload_run_id is not None and payload_run_id != run_id:
        raise HarnessValidationError("Harness payload run_id conflicts with canonical business context")
    payload_step_id = payload.get("step_id")
    if payload_step_id is not None and (
        step_id is None or payload_step_id != step_id
    ):
        raise HarnessValidationError("Harness payload step_id conflicts with canonical business context")
    duplicate_time_field = {
        "phase_recorded": "occurred_at",
        "decision_recorded": "decided_at",
        "step_state_changed": "updated_at",
    }.get(event_type)
    if duplicate_time_field is None or duplicate_time_field not in payload:
        return
    try:
        canonical_time = parse_datetime(occurred_at)
        duplicate_time = parse_datetime(payload.get(duplicate_time_field))
    except (TypeError, ValueError, OverflowError):
        canonical_time = None
        duplicate_time = None
    if canonical_time is None or duplicate_time is None or duplicate_time != canonical_time:
        raise HarnessValidationError(
            f"Harness payload {duplicate_time_field} conflicts with canonical occurred_at"
        )


def _optional_metadata_text(metadata: Mapping[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _canonical_harness_payload(event: HarnessEvent) -> dict[str, Any]:
    payload = thaw_canonical_json(event.payload)
    if not isinstance(payload, dict):
        raise HarnessValidationError("Harness payload must be an object")
    # These values are authoritative in EventPublishRequest/business_context.
    # Equal legacy duplicates are accepted by _validate_payload_context() above,
    # then removed so a new stored envelope has only one canonical owner.
    payload.pop("run_id", None)
    payload.pop("step_id", None)
    payload.pop("occurred_at", None)
    payload.pop("decided_at", None)
    payload["projection_schema"] = HARNESS_SAFE_PROJECTION
    event_type = event.event_type.value
    if event_type == "phase_recorded":
        payload["input_ref_checksums"] = _reference_checksums(
            payload.pop("input_refs", ()),
            field_name="input_refs",
        )
        payload["output_ref_checksums"] = _reference_checksums(
            payload.pop("output_refs", ()),
            field_name="output_refs",
        )
        if "gate_results" in payload:
            payload["gate_results"] = _gate_result_projections(
                payload["gate_results"]
            )
        return payload
    if event_type == "decision_recorded":
        decision_payload = payload.pop("payload", {})
        payload["decision_payload"] = _decision_payload_projection(decision_payload)
        reason = payload.pop("reason", None)
        if reason is not None:
            payload["reason_ref"] = _value_ref(reason)
        return payload
    if event_type == "worker_called":
        inputs = payload.pop("inputs", {})
        metadata = payload.pop("metadata", {})
        payload["input_ref"] = _value_ref(inputs)
        payload["input_count"] = len(inputs) if isinstance(inputs, Mapping) else 0
        payload["metadata_ref"] = _value_ref(metadata)
        return payload
    if event_type == "worker_result_recorded":
        output = payload.pop("output", {})
        artifacts = payload.pop("artifacts", ())
        diagnostics = payload.pop("diagnostics", {})
        metrics = payload.pop("metrics", {})
        error = payload.pop("error", None)
        payload["output_ref"] = _value_ref(output)
        artifact_refs = _reference_checksums(artifacts, field_name="artifacts")
        payload["artifact_count"] = len(artifact_refs)
        payload["artifact_ref_checksums"] = artifact_refs
        payload["diagnostics_ref"] = _value_ref(diagnostics)
        payload["metric_count"] = len(metrics) if isinstance(metrics, Mapping) else 0
        if error is not None:
            payload["error_ref"] = _value_ref(error)
        return payload
    if event_type == "gate_evaluated":
        details = payload.pop("details", {})
        if isinstance(details, Mapping) and isinstance(details.get("harness_gate"), Mapping):
            evidence = gate_result_evidence({**payload, "details": details})
            for key in (
                "reference",
                "input_ref",
                "result_ref",
                "reason_code",
                "score",
            ):
                if key in evidence:
                    payload[key] = evidence[key]
        payload["details_ref"] = _value_ref(details)
        reason = payload.pop("reason", None)
        if reason is not None:
            payload["reason_ref"] = _value_ref(reason)
        return payload
    if event_type == "step_state_changed":
        payload.pop("updated_at", None)
        output_ref = payload.pop("output_ref", None)
        if output_ref is not None:
            payload["output_key_ref"] = _value_ref(output_ref)
        metadata = payload.pop("metadata", {})
        payload["metadata"] = _step_metadata_projection(metadata)
        error = payload.pop("error", None)
        if error is not None:
            payload["error_ref"] = _value_ref(error)
        return payload
    return payload


def _decision_payload_projection(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {"value_ref": _value_ref(value)}
    projected: dict[str, Any] = {}
    for key in (
        "approval_outcome",
        "backoff_seconds",
        "max_turns",
        "turn_count",
    ):
        if key in value:
            projected[key] = thaw_canonical_json(value[key])
    gate_results = value.get("gate_results")
    if gate_results is not None:
        projected["gate_results"] = _gate_result_projections(gate_results)
    if "quality_verdict" in value:
        projected["quality_verdict_ref"] = _value_ref(value.get("quality_verdict"))
    if "side_effect_authorization" in value:
        authorization = _safe_side_effect_authorization_projection(
            value.get("side_effect_authorization")
        )
        projected["value_ref"] = authorization["decision_ref"]
    if "side_effect_failure" in value:
        failure = _safe_side_effect_failure_projection(
            value.get("side_effect_failure")
        )
        projected["value_ref"] = failure["effect_ref"]
    worker_value = value.get("worker_result", value)
    if any(key in value for key in ("worker_result", "status", "output", "diagnostics", "metrics", "error")):
        projected["worker_result_ref"] = _value_ref(worker_value)
    projected["decision_payload_ref"] = _value_ref(value)
    return projected


def _safe_side_effect_authorization_projection(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise HarnessValidationError("side-effect authorization projection must be an object")
    compact = {
        "origin",
        "effect_ref",
        "intent_ref",
        "identity_scope_ref",
        "subject_scope_ref",
        "approval_evidence_ref",
        "decision_ref",
        "disposition",
        "idempotency_ref",
    }
    legacy = compact | {
        "kind",
        "aggregate_verdict_ref",
        "atomic_group_ref",
        "effect_attempt",
        "effect_attempt_limit",
    }
    fields = set(value)
    if fields != compact and fields != legacy:
        raise HarnessValidationError("side-effect authorization projection fields are invalid")
    for field_name in (
        "effect_ref",
        "intent_ref",
        "identity_scope_ref",
        "subject_scope_ref",
        "approval_evidence_ref",
        "decision_ref",
        "idempotency_ref",
    ):
        if not _valid_checksum_ref(value.get(field_name)):
            raise HarnessValidationError(
                f"side-effect authorization {field_name} must be a sha256 reference"
            )
    if fields == legacy:
        if not _valid_checksum_ref(value.get("atomic_group_ref")):
            raise HarnessValidationError(
                "side-effect authorization atomic_group_ref must be a sha256 reference"
            )
        aggregate_verdict_ref = value.get("aggregate_verdict_ref")
        if aggregate_verdict_ref is not None and not _valid_checksum_ref(
            aggregate_verdict_ref
        ):
            raise HarnessValidationError(
                "side-effect authorization aggregate_verdict_ref must be a sha256 reference"
            )
        for field_name in ("effect_attempt", "effect_attempt_limit"):
            item = value.get(field_name)
            if isinstance(item, bool) or not isinstance(item, int) or item < 0:
                raise HarnessValidationError(
                    f"side-effect authorization {field_name} is invalid"
                )
        if (
            value["effect_attempt"] < 1
            or value["effect_attempt_limit"] < value["effect_attempt"]
        ):
            raise HarnessValidationError(
                "side-effect authorization attempt range is invalid"
            )
        if not isinstance(value.get("kind"), str) or not value["kind"].strip():
            raise HarnessValidationError("side-effect authorization kind is invalid")
    if value.get("origin") not in {"worker", "controller_terminal"}:
        raise HarnessValidationError("side-effect authorization origin is invalid")
    if value.get("disposition") not in {"candidate", "prepared", "quarantine", "accepted"}:
        raise HarnessValidationError("side-effect authorization disposition is invalid")
    return {key: thaw_canonical_json(value[key]) for key in sorted(fields)}


def _safe_side_effect_failure_projection(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise HarnessValidationError("side-effect failure projection must be an object")
    if set(value) != {"code", "effect_ref"}:
        raise HarnessValidationError("side-effect failure projection fields are invalid")
    code = value.get("code")
    if not isinstance(code, str) or not code.strip():
        raise HarnessValidationError("side-effect failure code is invalid")
    effect_ref = value.get("effect_ref")
    if not _valid_checksum_ref(effect_ref):
        raise HarnessValidationError("side-effect failure effect_ref must be a sha256 reference")
    return {"code": code.strip(), "effect_ref": effect_ref}


def _valid_checksum_ref(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    digest = value.removeprefix("sha256:")
    return len(digest) == 64 and all(
        character in "0123456789abcdef" for character in digest
    )


def _gate_result_projections(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list | tuple):
        raise HarnessValidationError("Harness gate_results must be an array")
    projected: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise HarnessValidationError("Harness gate result must be an object")
        gate = item.get("gate")
        passed = item.get("passed")
        if not isinstance(gate, str) or not gate.strip():
            raise HarnessValidationError("Harness gate result requires gate")
        if not isinstance(passed, bool):
            raise HarnessValidationError("Harness gate result passed must be a boolean")
        projected.append(
            {
                "gate": gate.strip(),
                "passed": passed,
                "result_ref": _value_ref(item),
            }
        )
    return projected


def _step_metadata_projection(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {"metadata_ref": _value_ref(value)}
    projected = {
        str(key): thaw_canonical_json(item)
        for key, item in value.items()
        if key in {"approval_granted", "rerouted"}
    }
    if "worker_result" in value:
        projected["worker_result_ref"] = _value_ref(value["worker_result"])
    if value:
        projected["metadata_ref"] = _value_ref(value)
    return projected


def _harness_metadata_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    omitted: dict[str, Any] = {}
    for key, item in value.items():
        if key in {"phase_index", "replan_count", "turn_count", "worker_call_count"}:
            if isinstance(item, bool) or not isinstance(item, int) or item < 0:
                raise HarnessValidationError(
                    f"Harness metadata {key} must be a non-negative integer"
                )
            projected[key] = item
        elif key in {"status_after", "status_before"}:
            if item not in _HARNESS_STATUS_VALUES:
                raise HarnessValidationError(f"Harness metadata {key} is invalid")
            projected[key] = item
        elif key == "transition_kind":
            if item not in _HARNESS_TRANSITION_KINDS:
                raise HarnessValidationError("Harness metadata transition_kind is invalid")
            projected[key] = item
        else:
            omitted[str(key)] = item
    if omitted:
        projected["omitted_metadata_count"] = len(omitted)
        projected["omitted_metadata_ref"] = _value_ref(omitted)
    return projected


def _reference_checksums(value: Any, *, field_name: str) -> list[str]:
    if not isinstance(value, list | tuple):
        raise HarnessValidationError(f"Harness {field_name} must be an array")
    return [_value_ref(item) for item in value]


def _legacy_trace_id(value: Any) -> str:
    if not isinstance(value, str):
        raise HarnessValidationError("legacy Harness trace_id must be a string")
    normalized = value.strip()
    if _LEGACY_TRACE_ID_PATTERN.fullmatch(normalized) is None:
        raise HarnessValidationError("legacy Harness trace_id has an unsafe format")
    return normalized.lower()


def _value_ref(value: Any) -> str:
    return checksum_for(thaw_canonical_json(value))


def _scoped_harness_event_id(
    event_id: str,
    *,
    identity_scope_ref: str | None,
) -> str:
    if identity_scope_ref is None or event_id.startswith("harness-event-v2:"):
        return event_id
    digest = hashlib.sha256(
        f"{identity_scope_ref}|{event_id}".encode("utf-8")
    ).hexdigest()
    return f"harness-event-v2:{digest}"


def _validate_transition_retry(
    committed: HarnessTransitionCommitted,
    candidate: HarnessTransitionCommitted,
) -> None:
    _validate_transition_retry_fields(
        committed,
        candidate,
        fields=(
        "transition_id",
        "run_id",
        "transition_kind",
        "from_version",
        "state_version",
        "before_state_checksum",
        "after_state_checksum",
        "decision_ref",
        "gate_ref",
        "budget_ref",
        "activity_result_ref",
        "activity_result_event_id",
        "activity_id",
        "idempotency_key",
        "identity_scope_ref",
        "reducer_version",
        "policy_version",
        "schema_version",
        ),
    )


def _validate_legacy_transition_retry(
    committed: HarnessTransitionCommitted,
    candidate: HarnessTransitionCommitted,
) -> None:
    if (
        committed.identity_scope_ref is not None
        or committed.transition_id != legacy_transition_id(candidate)
    ):
        raise EventReplayMismatchError(
            sequence=committed.stream_sequence or committed.state_version,
            reason="legacy Harness transition identity is not equivalent",
        )
    _validate_transition_retry_fields(
        committed,
        candidate,
        fields=(
            "run_id",
            "transition_kind",
            "from_version",
            "state_version",
            "before_state_checksum",
            "after_state_checksum",
            "decision_ref",
            "gate_ref",
            "budget_ref",
            "activity_result_ref",
            "activity_result_event_id",
            "activity_id",
            "idempotency_key",
            "reducer_version",
            "policy_version",
            "schema_version",
        ),
    )


def _validate_transition_retry_fields(
    committed: HarnessTransitionCommitted,
    candidate: HarnessTransitionCommitted,
    *,
    fields: tuple[str, ...],
) -> None:
    for field_name in fields:
        if getattr(committed, field_name) != getattr(candidate, field_name):
            raise EventReplayMismatchError(
                sequence=committed.stream_sequence or committed.state_version,
                reason=f"Harness transition retry conflicts at {field_name}",
            )
    if committed.state.to_dict() != candidate.state.to_dict():
        raise EventReplayMismatchError(
            sequence=committed.stream_sequence or committed.state_version,
            reason="Harness transition retry conflicts with committed state",
        )


def _validate_harness_activity_descriptor(
    descriptor: ReplayActivityDescriptor,
    expected: HarnessActivity,
) -> None:
    expected_context = {
        "run_id": expected.run_id,
        "step_id": expected.step_id,
        "activity_type": expected.activity_type,
        "identity_scope_ref": expected.identity_scope_ref,
    }
    if (
        descriptor.activity_id != expected.activity_id
        or descriptor.activity_kind
        is not harness_activity_kind(expected.activity_type)
        or descriptor.input_checksum != expected.input_checksum
        or descriptor.idempotency_key != expected.idempotency_key
        or descriptor.attempt != expected.attempt
        or descriptor.contract_version != expected.contract_version
        or descriptor.handler_version != expected.worker_version
        or thaw_canonical_json(descriptor.context) != expected_context
    ):
        raise EventStoreCorruptionError(
            "committed Harness activity descriptor conflicts with state"
        )


def _worker_status_from_outcome(outcome: ReplayActivityOutcome) -> str:
    if outcome.status is ReplayActivityStatus.SUCCEEDED:
        return HarnessWorkerStatus.SUCCEEDED.value
    error_class = outcome.error_class
    prefix = "harness_worker_"
    if not isinstance(error_class, str) or not error_class.startswith(prefix):
        raise EventStoreCorruptionError(
            "recorded Harness activity has an invalid error class"
        )
    status = error_class.removeprefix(prefix)
    if status not in {
        HarnessWorkerStatus.FAILED.value,
        HarnessWorkerStatus.BLOCKED.value,
        HarnessWorkerStatus.WAITING_APPROVAL.value,
    }:
        raise EventStoreCorruptionError(
            "recorded Harness activity has an unsupported worker status"
        )
    return status


def _worker_result_from_recorded_activity(
    store: RecordedActivityStorePort,
    resolved: ResolvedReplayActivity,
) -> HarnessWorkerResult:
    status = _worker_status_from_outcome(resolved.outcome)
    payload_ref = (
        resolved.outcome.output_ref
        if resolved.outcome.status is ReplayActivityStatus.SUCCEEDED
        else resolved.outcome.error_ref
    )
    if payload_ref is None:
        raise ReplayActivityIncompleteError(
            "recorded Harness activity is missing its terminal payload"
        )
    try:
        value = store.get_payload(
            payload_ref,
            tenant_id=resolved.activity.tenant_id,
        )
    except (ReplayActivityMissingError, ReplayActivityCorruptionError):
        raise
    except LookupError as exc:
        raise ReplayActivityMissingError(
            "recorded Harness activity terminal payload is missing"
        ) from exc
    except EventStoreCorruptionError as exc:
        raise ReplayActivityCorruptionError(
            "recorded Harness activity terminal payload is corrupt"
        ) from exc
    try:
        actual_checksum = checksum_for(value)
        payload = thaw_canonical_json(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ReplayActivityCorruptionError(
            "recorded Harness activity terminal payload is not canonical"
        ) from exc
    if actual_checksum != payload_ref.expected_checksum:
        raise ReplayActivityCorruptionError(
            "recorded Harness activity terminal payload checksum does not match"
        )
    expected_fields = {
        "status",
        "output",
        "artifacts",
        "diagnostics",
        "metrics",
        "error",
    }
    actual_fields = set(payload) if isinstance(payload, Mapping) else set()
    if not isinstance(payload, Mapping) or actual_fields not in {
        frozenset(expected_fields),
        frozenset((*expected_fields, "effect_intent")),
    }:
        raise ReplayActivityCorruptionError(
            "recorded Harness worker result payload is invalid"
        )
    output = payload.get("output")
    artifacts = payload.get("artifacts")
    diagnostics = payload.get("diagnostics")
    metrics = payload.get("metrics")
    error = payload.get("error")
    if (
        not isinstance(output, Mapping)
        or not isinstance(artifacts, list | tuple)
        or any(not isinstance(item, str) for item in artifacts)
        or not isinstance(diagnostics, Mapping)
        or not isinstance(metrics, Mapping)
        or (error is not None and not isinstance(error, str))
    ):
        raise ReplayActivityCorruptionError(
            "recorded Harness worker result fields are invalid"
        )
    try:
        result = HarnessWorkerResult(
            status=payload.get("status"),
            output=dict(output),
            artifacts=tuple(artifacts),
            diagnostics=dict(diagnostics),
            metrics=dict(metrics),
            error=error,
            effect_intent=payload.get("effect_intent"),
        )
    except (HarnessValidationError, TypeError, ValueError) as exc:
        raise ReplayActivityCorruptionError(
            "recorded Harness worker result cannot be restored"
        ) from exc
    if result.status.value != status:
        raise ReplayActivityCorruptionError(
            "recorded Harness worker status conflicts with activity outcome"
        )
    return result


def _validate_harness_activity_extension(
    extension: Mapping[str, Any],
    *,
    expected: HarnessActivity,
    resolved: ResolvedReplayActivity,
    occurred_at: datetime,
) -> None:
    expected_fields = {
        "schema",
        "activity",
        "status",
        "input_ref",
        "output_ref",
        "error_ref",
        "error_class",
        "accepted_at",
        "started_at",
        "completed_at",
    }
    if set(extension) != expected_fields:
        raise EventStoreCorruptionError(
            "committed Harness activity extension fields are invalid"
        )
    try:
        input_ref = PayloadReference.from_dict(extension["input_ref"])
        output_ref = _optional_payload_reference(extension.get("output_ref"))
        error_ref = _optional_payload_reference(extension.get("error_ref"))
        accepted_at = parse_datetime(extension.get("accepted_at"))
        started_at = parse_datetime(extension.get("started_at"))
        completed_at = parse_datetime(extension.get("completed_at"))
    except (KeyError, TypeError, ValueError) as exc:
        raise EventStoreCorruptionError(
            "committed Harness activity extension is corrupt"
        ) from exc
    if (
        extension.get("schema") != REPLAY_ACTIVITY_RECORD_SCHEMA
        or HarnessActivity.from_dict(extension["activity"]) != expected
        or extension.get("status") != _worker_status_from_outcome(resolved.outcome)
        or input_ref != resolved.activity.input_ref
        or output_ref != resolved.outcome.output_ref
        or error_ref != resolved.outcome.error_ref
        or extension.get("error_class") != resolved.outcome.error_class
        or accepted_at != resolved.activity.accepted_at
        or started_at != resolved.outcome.started_at
        or completed_at != resolved.outcome.completed_at
        or occurred_at != resolved.outcome.completed_at
    ):
        raise EventStoreCorruptionError(
            "committed Harness activity extension conflicts with recorded history"
        )


def _optional_payload_reference(value: Any) -> PayloadReference | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TypeError("payload reference must be an object")
    return PayloadReference.from_dict(value)


def _activity_from_step_metadata(
    run_spec: HarnessRunSpec,
    step: HarnessStepState,
) -> HarnessActivity | None:
    activity_id = step.metadata.get("activity_id")
    if activity_id is None:
        return None
    step_spec = next(
        (item for item in run_spec.workflow.steps if item.step_id == step.step_id),
        None,
    )
    if step_spec is None:  # pragma: no cover - HarnessState already validates this
        raise EventStoreCorruptionError("Harness activity references an unknown step")
    required = {
        "activity_type": step.metadata.get("activity_type", step_spec.worker_type.value),
        "contract_version": step.metadata.get("activity_contract_version"),
        "idempotency_key": step.metadata.get("activity_idempotency_key"),
        "input_checksum": step.metadata.get("activity_input_checksum"),
        "worker_version": step.metadata.get("activity_worker_version"),
    }
    if any(value is None for value in required.values()):
        raise EventStoreCorruptionError(
            "Harness projected activity descriptor is incomplete"
        )
    try:
        return HarnessActivity(
            activity_id=str(activity_id),
            run_id=run_spec.run_id,
            step_id=step.step_id,
            attempt=int(step.metadata.get("activity_attempt", step.attempts)),
            activity_type=str(required["activity_type"]),
            contract_version=str(required["contract_version"]),
            idempotency_key=str(required["idempotency_key"]),
            input_checksum=str(required["input_checksum"]),
            identity_scope_ref=(
                None
                if step.metadata.get("activity_identity_scope_ref") is None
                else str(step.metadata["activity_identity_scope_ref"])
            ),
            worker_version=str(required["worker_version"]),
        )
    except (HarnessValidationError, TypeError, ValueError) as exc:
        raise EventStoreCorruptionError(
            "Harness projected activity descriptor is invalid"
        ) from exc


def _activity_extension_id(extension: Mapping[str, Any]) -> str:
    activity = extension.get("activity")
    if not isinstance(activity, Mapping):
        raise HarnessValidationError("stored Harness activity descriptor is missing")
    activity_id = activity.get("activity_id")
    if not isinstance(activity_id, str) or not activity_id.strip():
        raise HarnessValidationError("stored Harness activity_id is invalid")
    return activity_id


def _stored_deterministic_history(event: StoredEvent) -> dict[str, Any]:
    value = thaw_canonical_json(
        event.extensions.get(DETERMINISTIC_HISTORY_EXTENSION, {})
    )
    if not isinstance(value, Mapping):
        raise HarnessValidationError(
            "stored Harness deterministic history must be an object"
        )
    try:
        return DeterministicHistoryRecord.from_dict(value).to_dict()
    except (TypeError, ValueError) as exc:
        raise HarnessValidationError(
            "stored Harness deterministic history is invalid"
        ) from exc


def _called_activity_ids_for_recovery(
    *,
    state: HarnessState | None,
    transitions: tuple[HarnessTransitionCommitted, ...],
    stored_events: tuple[StoredEvent, ...],
    tenant_id: str | None,
    classification: SecurityClassification,
) -> frozenset[str]:
    if (
        state is None
        or not transitions
        or transitions[-1].transition_kind != HarnessTransitionKind.EXECUTE_ENTRY
        or state.current_step_id is None
    ):
        return frozenset()
    transition = transitions[-1]
    if transition.stream_sequence is None:
        raise EventStoreCorruptionError(
            "Harness execute entry is missing its durable stream sequence"
        )
    step = next(
        item for item in state.step_states if item.step_id == state.current_step_id
    )
    activity = _activity_from_step_metadata(state.run_spec, step)
    if activity is None:
        return frozenset()
    markers = tuple(
        event
        for event in stored_events
        if event.event_type == "worker_called"
        and event.stream_sequence > transition.stream_sequence
    )
    if not markers:
        return frozenset()
    if len(markers) != 1:
        raise EventStoreCorruptionError(
            "Harness execute entry has duplicate worker call markers"
        )
    marker = markers[0]
    try:
        _validate_stored_harness_event(marker)
    except (EventIntegrityError, HarnessValidationError, TypeError) as exc:
        raise EventStoreCorruptionError(
            "Harness worker call marker envelope is invalid"
        ) from exc
    if (
        marker.stream_id != f"run:{state.run_spec.run_id}"
        or marker.subject != activity.step_id
        or marker.correlation_id != state.run_spec.run_id
        or marker.business_context.run_id != state.run_spec.run_id
        or marker.business_context.step_id != activity.step_id
        or marker.tenant_id != tenant_id
        or marker.security_classification != classification
    ):
        raise EventStoreCorruptionError(
            "Harness worker call marker context conflicts with activity"
        )
    payload = thaw_canonical_json(marker.payload or {})
    if not isinstance(payload, Mapping):
        raise EventStoreCorruptionError(
            "Harness worker call marker payload is invalid"
        )
    if payload.get("projection_schema") != HARNESS_SAFE_PROJECTION:
        raise EventStoreCorruptionError(
            "Harness worker call marker projection schema is invalid"
        )
    validate_activity_call_marker(payload, expected_activity=activity)
    return frozenset({activity.activity_id})


def _coerce_output_sequence(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list | tuple | set | frozenset):
        return tuple(str(item) for item in value)
    return (str(value),)


__all__ = [
    "DurableHarnessEventPort",
    "DurableHarnessTransitionPort",
    "HARNESS_DATA_SCHEMA",
    "HARNESS_EVENT_SOURCE",
    "HARNESS_SAFE_PROJECTION",
    "HarnessRecovery",
    "HarnessEventCanonicalAdapter",
    "HarnessTransitionCommit",
]
