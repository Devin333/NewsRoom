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
from framework.events.runtime.publisher import EventPublishRequest
from framework.events.schema.security import SecurityClassification
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.event import HarnessEvent
from framework.harness.control_plane.event_log import (
    HarnessEventLogEntry,
    event_log_entry_from_stored_event,
)
from framework.harness.control_plane.activity import (
    HARNESS_ACTIVITY_EXTENSION,
    HARNESS_ACTIVITY_RESULT_SCHEMA,
    HarnessActivity,
    HarnessActivityResultRecord,
    SecureHarnessActivityStorePort,
    resolve_activity_result,
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
from framework.harness.workers.result import HarnessWorkerResult
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
            extensions={"harness": harness_extension},
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
        )

    def to_activity_result_publish_request(
        self,
        record: HarnessActivityResultRecord,
        reference: PayloadReference,
    ) -> EventPublishRequest:
        if not isinstance(record, HarnessActivityResultRecord):
            raise TypeError("record must be HarnessActivityResultRecord")
        if not isinstance(reference, PayloadReference):
            raise TypeError("reference must be PayloadReference")
        activity = record.activity
        if activity.identity_scope_ref != self.identity_scope_ref:
            raise HarnessValidationError(
                "Harness activity identity scope conflicts with adapter tenant"
            )
        run_id = validate_artifact_path_segment(activity.run_id, field="run_id")
        return EventPublishRequest(
            event_id=activity.result_event_id,
            event_type="worker_result_recorded",
            data_schema=HARNESS_DATA_SCHEMA,
            source=HARNESS_EVENT_SOURCE,
            subject=activity.step_id,
            occurred_at=record.completed_at,
            stream_id=f"run:{run_id}",
            correlation_id=run_id,
            business_context=BusinessContext(
                run_id=run_id,
                step_id=activity.step_id,
            ),
            producer=self.producer,
            tenant_id=self.tenant_id,
            security_classification=self.activity_security_classification,
            content_type=reference.content_type,
            payload_ref=reference,
            extensions={
                HARNESS_ACTIVITY_EXTENSION: {
                    "schema": HARNESS_ACTIVITY_RESULT_SCHEMA,
                    "activity": activity.to_dict(),
                    "status": record.result.status.value,
                    "result_checksum": record.content_checksum,
                    "completed_at": format_datetime(record.completed_at),
                }
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
        )


class DurableHarnessEventPort:
    """Harness sink whose projection advances only after canonical commit."""

    def __init__(
        self,
        runtime: EventRuntimePort,
        *,
        reader: EventReaderPort | None = None,
        secure_activity_store: SecureHarnessActivityStorePort | None = None,
        adapter: HarnessEventCanonicalAdapter | None = None,
        projector: HarnessStateProjector | None = None,
    ) -> None:
        if runtime is None:
            raise HarnessValidationError("event runtime is required")
        self._runtime = runtime
        self._reader = reader
        self._secure_activity_store = secure_activity_store
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
    ) -> HarnessActivity:
        self.require_activity_storage()
        return HarnessActivity.for_worker_call(
            run_id=run_id,
            step_id=step_id,
            attempt=attempt,
            activity_type=activity_type,
            inputs=inputs,
            identity_scope_ref=self._adapter.identity_scope_ref,
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
        if self._secure_activity_store is None:
            raise EventIncompleteHistoryError(
                "durable Harness worker execution requires a secure activity result store"
            )
        if self._adapter.tenant_id is None:
            raise EventIncompleteHistoryError(
                "durable Harness worker execution requires an authoritative tenant"
            )

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
            if recovered.to_worker_result().to_dict() != result.to_dict():
                raise EventReplayMismatchError(
                    sequence=existing.stream_sequence,
                    reason="Harness activity retry produced a different result",
                )
            projected = self._adapter.from_stored_event(existing)
            self._append_compatibility_projection(existing, projected)
            return projected

        self.require_activity_storage()
        assert self._secure_activity_store is not None
        assert self._adapter.tenant_id is not None
        classification = SecurityClassification(
            self._adapter.activity_security_classification
        )
        record = HarnessActivityResultRecord(
            activity=activity,
            result=result,
            completed_at=completed_at,
        )
        reference = self._secure_activity_store.put_result(
            record,
            tenant_id=self._adapter.tenant_id,
            classification=classification,
        )
        if not isinstance(reference, PayloadReference):
            raise EventStoreCorruptionError(
                "secure Harness activity store returned an invalid reference"
            )
        validation = self._secure_activity_store.validate_reference(
            reference.to_dict(),
            tenant_id=self._adapter.tenant_id,
            classification=classification,
        )
        if not validation.proves(
            reference.to_dict(),
            tenant_id=self._adapter.tenant_id,
            classification=classification,
        ):
            raise EventStoreCorruptionError(
                "secure Harness activity store returned an unverified reference"
            )
        request = self._adapter.to_activity_result_publish_request(record, reference)
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
        resolved_records: dict[str, HarnessActivityResultRecord] = {}

        def resolve_record(
            event_id: str,
            activity: HarnessActivity,
        ) -> HarnessActivityResultRecord:
            event = by_id.get(event_id)
            if event is None:
                raise EventIncompleteHistoryError(
                    "Harness history is missing a committed worker activity result"
                )
            record = resolved_records.get(event_id)
            if record is None:
                record = self._resolve_activity_event(event, expected=activity)
                resolved_records[event_id] = record
            elif record.activity != activity:
                raise EventStoreCorruptionError(
                    "Harness activity result is referenced by conflicting activities"
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
            worker_result = record.to_worker_result()
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
            ).to_worker_result()
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
    ) -> HarnessActivityResultRecord:
        self.require_activity_storage()
        assert self._secure_activity_store is not None
        assert self._adapter.tenant_id is not None
        event.verify_integrity()
        if (
            event.event_id != expected.result_event_id
            or event.event_type != "worker_result_recorded"
            or event.data_schema != HARNESS_DATA_SCHEMA
            or event.business_context.run_id != expected.run_id
            or event.business_context.step_id != expected.step_id
            or event.payload_ref is None
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
        return resolve_activity_result(
            self._secure_activity_store,
            event.payload_ref,
            expected_activity=expected,
            tenant_id=self._adapter.tenant_id,
            classification=SecurityClassification(event.security_classification),
        )

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
        secure_activity_store: SecureHarnessActivityStorePort | None = None,
        adapter: HarnessEventCanonicalAdapter | None = None,
        projector: HarnessStateProjector | None = None,
    ) -> None:
        super().__init__(
            runtime,
            reader=reader,
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
    worker_value = value.get("worker_result", value)
    if any(key in value for key in ("worker_result", "status", "output", "diagnostics", "metrics", "error")):
        projected["worker_result_ref"] = _value_ref(worker_value)
    projected["decision_payload_ref"] = _value_ref(value)
    return projected


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
