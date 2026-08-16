from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from threading import RLock
from typing import Any

from framework.agent.artifacts.paths import validate_artifact_path_segment
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
from framework.events.runtime.models import StreamReadRequest, StreamSequenceCursor
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
    harness_graph_history,
)
from framework.harness.control_plane.activity import (
    HARNESS_ACTIVITY_CONTRACT,
    HARNESS_ACTIVITY_EXTENSION,
    HarnessActivity,
    harness_activity_input_checksum,
    validate_activity_call_marker,
)
from framework.harness.control_plane.graph_decision import HarnessGraphDecision
from framework.harness.control_plane.graph_evaluator import (
    HarnessAcceptedGraphObservation,
    HarnessGraphObservationType,
)
from framework.harness.control_plane.graph_runtime import (
    HARNESS_GRAPH_COMMIT_SCHEMA,
    HARNESS_GRAPH_PROJECTION_RECORD_SCHEMA,
    HarnessGraphActivity,
    HarnessGraphActivityResult,
    HarnessGraphActivityResultCommit,
    HarnessGraphCommitKind,
    HarnessGraphDecisionCommit,
    HarnessGraphObservationCommit,
    HarnessGraphProjectionCommit,
    HarnessGraphRecovery,
    _counter_delta,
    _validate_graph_activity_binding,
    _validate_graph_decision_storage_identity,
    validate_graph_activity_result,
)
from framework.harness.control_plane.graph_result_lineage import (
    HarnessGraphResultLineage,
)
from framework.harness.control_plane.graph_state import HarnessGraphState
from framework.harness.control_plane.transition import (
    HARNESS_EVENT_SOURCE,
    HARNESS_TRANSITION_DATA_SCHEMA,
    HARNESS_TRANSITION_EVENT_TYPE,
    HarnessTransitionCommitted,
)
from framework.harness.quality.verdict import gate_result_evidence
from framework.harness.graph.model import (
    HarnessContractReference,
    HarnessExecutableNode,
    NormalizedHarnessGraph,
)
from framework.harness.graph.versioning import (
    HARNESS_GRAPH_REDUCER_VERSION,
    HARNESS_GRAPH_STATE_SCHEMA,
)
from framework.harness.workers.result import HarnessWorkerResult, HarnessWorkerStatus
from framework.events.budget import CanonicalBudgetEventSink, DurableBudgetFactResolver
from framework.shared.time import format_datetime, parse_datetime


HARNESS_DATA_SCHEMA = "newsroom.harness-event/v1"
HARNESS_SAFE_PROJECTION = "harness-safe-summary/v1"
HARNESS_GRAPH_INITIALIZED_EVENT_TYPE = "harness_graph_initialized"
HARNESS_GRAPH_DECISION_EVENT_TYPE = "harness_graph_decision_committed"
HARNESS_GRAPH_PROJECTION_EVENT_TYPE = "harness_graph_projection_committed"
HARNESS_GRAPH_ACTIVITY_RESULT_EVENT_TYPE = "harness_graph_activity_result_committed"
HARNESS_GRAPH_OBSERVATION_EVENT_TYPE = "harness_graph_observation_committed"
HARNESS_GRAPH_EVENT_TYPES = frozenset(
    {
        HARNESS_GRAPH_INITIALIZED_EVENT_TYPE,
        HARNESS_GRAPH_DECISION_EVENT_TYPE,
        HARNESS_GRAPH_PROJECTION_EVENT_TYPE,
        HARNESS_GRAPH_ACTIVITY_RESULT_EVENT_TYPE,
        HARNESS_GRAPH_OBSERVATION_EVENT_TYPE,
    }
)
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
class _ResolvedHarnessActivity:
    activity: ResolvedReplayActivity
    worker_result: HarnessWorkerResult


@dataclass(frozen=True, slots=True)
class _HarnessGraphProjectionRecord:
    """Bounded durable record whose full state is reproduced by the reducer."""

    commit_kind: HarnessGraphCommitKind | str
    run_id: str
    cause_checksum: str
    previous_projection_checksum: str
    projection_checksum: str
    sequence: int
    occurred_at: datetime
    budget_reservations: Mapping[str, Any]
    budget_consumptions: Mapping[str, Any]
    activity: HarnessGraphActivity | None
    state_summary: Mapping[str, Any]
    activated_node_instance_id: str | None
    projection_commit_checksum: str
    state_schema_version: str = HARNESS_GRAPH_STATE_SCHEMA
    reducer_version: str = HARNESS_GRAPH_REDUCER_VERSION
    schema_version: str = HARNESS_GRAPH_PROJECTION_RECORD_SCHEMA
    record_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        commit_kind = HarnessGraphCommitKind(self.commit_kind)
        if commit_kind not in {
            HarnessGraphCommitKind.DECISION_PROJECTION,
            HarnessGraphCommitKind.ACTIVITY_RESULT_PROJECTION,
            HarnessGraphCommitKind.OBSERVATION_PROJECTION,
        }:
            raise HarnessValidationError(
                "durable graph projection record has an invalid kind",
                code="invalid_graph_projection_record_kind",
            )
        run_id = validate_artifact_path_segment(self.run_id, field="run_id")
        cause_checksum = _graph_checksum(self.cause_checksum, "cause_checksum")
        previous_projection_checksum = _graph_checksum(
            self.previous_projection_checksum,
            "previous_projection_checksum",
        )
        projection_checksum = _graph_checksum(
            self.projection_checksum,
            "projection_checksum",
        )
        projection_commit_checksum = _graph_checksum(
            self.projection_commit_checksum,
            "projection_commit_checksum",
        )
        if (
            not isinstance(self.sequence, int)
            or isinstance(self.sequence, bool)
            or self.sequence < 2
        ):
            raise HarnessValidationError(
                "durable graph projection record sequence must be at least two",
                code="invalid_graph_projection_record_sequence",
            )
        occurred_at = parse_datetime(self.occurred_at)
        if occurred_at is None:
            raise HarnessValidationError(
                "durable graph projection record requires occurred_at",
                code="invalid_graph_projection_record_time",
            )
        reservations = _counter_delta(
            self.budget_reservations,
            "budget_reservations",
        )
        consumptions = _counter_delta(
            self.budget_consumptions,
            "budget_consumptions",
        )
        if reservations != consumptions:
            raise HarnessValidationError(
                "durable graph projection budget deltas must match",
                code="graph_budget_reservation_mismatch",
            )
        if self.activity is not None and not isinstance(
            self.activity,
            HarnessGraphActivity,
        ):
            raise TypeError("activity must be HarnessGraphActivity or None")
        state_summary = _graph_mapping(self.state_summary, "state_summary")
        if len(state_summary) > 8:
            raise HarnessValidationError(
                "durable graph projection state summary is too broad",
                code="graph_projection_summary_too_broad",
            )
        activated_node_instance_id = (
            None
            if self.activated_node_instance_id is None
            else _graph_required_text(
                self.activated_node_instance_id,
                "activated_node_instance_id",
            )
        )
        if self.state_schema_version != HARNESS_GRAPH_STATE_SCHEMA:
            raise HarnessValidationError(
                "durable graph projection requires the pinned state schema",
                code="unsupported_graph_projection_state_schema",
            )
        if self.reducer_version != HARNESS_GRAPH_REDUCER_VERSION:
            raise HarnessValidationError(
                "durable graph projection requires the pinned reducer",
                code="unsupported_graph_projection_reducer",
            )
        if self.schema_version != HARNESS_GRAPH_PROJECTION_RECORD_SCHEMA:
            raise HarnessValidationError(
                "unsupported durable graph projection record schema",
                code="unsupported_graph_projection_record_schema",
            )
        object.__setattr__(self, "commit_kind", commit_kind)
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "cause_checksum", cause_checksum)
        object.__setattr__(
            self,
            "previous_projection_checksum",
            previous_projection_checksum,
        )
        object.__setattr__(self, "projection_checksum", projection_checksum)
        object.__setattr__(
            self,
            "projection_commit_checksum",
            projection_commit_checksum,
        )
        object.__setattr__(self, "occurred_at", occurred_at)
        object.__setattr__(self, "budget_reservations", reservations)
        object.__setattr__(self, "budget_consumptions", consumptions)
        object.__setattr__(self, "state_summary", dict(state_summary))
        object.__setattr__(
            self,
            "activated_node_instance_id",
            activated_node_instance_id,
        )
        object.__setattr__(
            self,
            "record_checksum",
            checksum_for(self.checksum_projection()),
        )

    @classmethod
    def from_commit(
        cls,
        commit: HarnessGraphProjectionCommit,
    ) -> "_HarnessGraphProjectionRecord":
        if not isinstance(commit, HarnessGraphProjectionCommit):
            raise TypeError("commit must be HarnessGraphProjectionCommit")
        if commit.commit_kind is HarnessGraphCommitKind.INITIALIZE:
            raise HarnessValidationError(
                "graph initialization cannot use a compact projection record",
                code="invalid_graph_projection_record_kind",
            )
        activated = _activated_node_for_projection(commit)
        return cls(
            commit_kind=commit.commit_kind,
            run_id=commit.state.run_id,
            cause_checksum=commit.cause_checksum,
            previous_projection_checksum=(
                commit.previous_projection_checksum or ""
            ),
            projection_checksum=commit.state.projection_checksum,
            sequence=commit.sequence,
            occurred_at=commit.occurred_at,
            budget_reservations=commit.budget_reservations,
            budget_consumptions=commit.budget_consumptions,
            activity=commit.activity,
            state_summary=_graph_projection_state_summary(commit.state),
            activated_node_instance_id=(
                None if activated is None else activated.instance_id
            ),
            projection_commit_checksum=commit.commit_checksum,
        )

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "state_schema_version": self.state_schema_version,
            "reducer_version": self.reducer_version,
            "commit_kind": self.commit_kind.value,
            "run_id": self.run_id,
            "cause_checksum": self.cause_checksum,
            "previous_projection_checksum": self.previous_projection_checksum,
            "projection_checksum": self.projection_checksum,
            "sequence": self.sequence,
            "occurred_at": format_datetime(self.occurred_at),
            "budget_reservations": dict(self.budget_reservations),
            "budget_consumptions": dict(self.budget_consumptions),
            "activity": None if self.activity is None else self.activity.to_dict(),
            "state_summary": dict(self.state_summary),
            "activated_node_instance_id": self.activated_node_instance_id,
            "projection_commit_checksum": self.projection_commit_checksum,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "record_checksum": self.record_checksum}


def _graph_projection_state_summary(state: HarnessGraphState) -> dict[str, Any]:
    raw = state.to_dict()
    node_summaries = []
    for node in raw.get("node_instances", ()):
        if not isinstance(node, Mapping):
            continue
        node_summaries.append(
            {
                "identity": node.get("identity"),
                "step_status": node.get("step_status"),
                "attempt": node.get("attempt"),
                "error_code": node.get("error_code"),
            }
        )
    return {
        "lifecycle": raw.get("lifecycle"),
        "outcome": raw.get("outcome"),
        "terminal_reason_code": raw.get("terminal_reason_code"),
        "node_instances": node_summaries,
        "active_activities": raw.get("active_activities", ()),
        "budgets": raw.get("budgets", {"counters": ()}),
    }


@dataclass(frozen=True, slots=True)
class _StoredHarnessGraphCommit:
    event_type: str
    commit: (
        HarnessGraphDecisionCommit
        | HarnessGraphProjectionCommit
        | HarnessGraphActivityResultCommit
        | HarnessGraphObservationCommit
        | _HarnessGraphProjectionRecord
    )
    graph: NormalizedHarnessGraph | None = None
    run_spec_checksum: str | None = None


@dataclass(frozen=True, slots=True)
class HarnessEventCanonicalAdapter:
    """Maps typed Harness facts to and from the canonical durable boundary."""

    producer: ProducerIdentity = ProducerIdentity(
        component="framework.harness.control_plane",
        version="1",
    )
    tenant_id: str | None = None
    security_classification: SecurityClassification | str = (
        SecurityClassification.INTERNAL
    )
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
            history = DeterministicHistoryRecord.from_dict(event.deterministic_history)
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
            raise HarnessValidationError(
                "Harness activity event requires a terminal record"
            )
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
                DETERMINISTIC_HISTORY_EXTENSION: harness_activity_history(
                    recorded
                ).to_dict(),
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
            raise HarnessValidationError(
                "stored Harness event requires business_context.run_id"
            )
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
        self._on_canonical_event_committed(stored)
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
        return tuple(
            entry for entry in self.event_log_entries if entry.run_id == run_id
        )

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
        if activity.identity_scope_ref != self._adapter.identity_scope_ref:
            raise HarnessValidationError(
                "Harness activity identity scope conflicts with adapter tenant"
            )
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

    def resolve_graph_replay_activity(
        self,
        activity: HarnessGraphActivity,
        graph: NormalizedHarnessGraph,
        inputs: Mapping[str, Any] | None = None,
    ) -> HarnessWorkerResult:
        """Resolve immutable graph activity history without accepting new work."""

        if not isinstance(activity, HarnessGraphActivity):
            raise TypeError("activity must be HarnessGraphActivity")
        if not isinstance(graph, NormalizedHarnessGraph):
            raise TypeError("graph must be NormalizedHarnessGraph")
        if inputs is not None and not isinstance(inputs, Mapping):
            raise TypeError("inputs must be a mapping or None")
        expected = _legacy_graph_activity_descriptor(activity, graph)
        if inputs is not None and (
            harness_activity_input_checksum(inputs) != expected.input_checksum
        ):
            raise EventReplayMismatchError(
                sequence=activity.causal_decision_sequence,
                reason="graph replay activity input conflicts with its descriptor",
            )
        event = self._require_reader().get_event(
            expected.result_event_id,
            tenant_id=self._adapter.tenant_id,
        )
        if event is None:
            raise EventIncompleteHistoryError(
                "graph activity result evidence is missing"
            )
        return self._resolve_activity_event(
            event,
            expected=expected,
        ).worker_result

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
        self._on_canonical_event_committed(stored)
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
            high_watermark = (
                reader.get_stream_high_watermark(
                    stream_id,
                    tenant_id=self._adapter.tenant_id,
                )
                or 0
            )
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
        if (
            descriptor is None
            or recorded_ref is None
            or recorded_ref != event.payload_ref
        ):
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

    def budget_fact_resolver(self) -> DurableBudgetFactResolver:
        return DurableBudgetFactResolver(
            self._require_reader(),
            tenant_id=self._adapter.tenant_id,
        )

    def budget_event_sink(self) -> CanonicalBudgetEventSink:
        return CanonicalBudgetEventSink(
            self._runtime,
            tenant_id=self._adapter.tenant_id,
        )

    def _on_canonical_event_committed(self, event: StoredEvent) -> None:
        """Allow graph-aware subclasses to advance a validated local snapshot."""

        del event


class DurableHarnessTransitionPort(DurableHarnessEventPort):
    def __init__(
        self,
        runtime: EventRuntimePort,
        reader: EventReaderPort,
        *,
        activity_store: RecordedActivityStorePort | None = None,
        secure_activity_store: RecordedActivityStorePort | None = None,
        adapter: HarnessEventCanonicalAdapter | None = None,
    ) -> None:
        super().__init__(
            runtime,
            reader=reader,
            activity_store=activity_store,
            secure_activity_store=secure_activity_store,
            adapter=adapter,
        )
        self._graph_snapshot_lock = RLock()
        self._graph_snapshots: dict[str, HarnessGraphRecovery] = {}

    def initialize_graph(
        self,
        graph: NormalizedHarnessGraph,
        state: HarnessGraphState,
        *,
        run_spec_checksum: str,
        occurred_at: datetime,
        expected_last_sequence: int,
    ) -> HarnessGraphProjectionCommit:
        if not isinstance(graph, NormalizedHarnessGraph):
            raise TypeError("graph must be NormalizedHarnessGraph")
        if not isinstance(state, HarnessGraphState):
            raise TypeError("state must be HarnessGraphState")
        _validate_graph_adapter_scope(state, self._adapter)
        run_spec_ref = _graph_checksum(run_spec_checksum, "run_spec_checksum")
        raw_event_id = _graph_initial_event_id(state.run_id, graph.checksum)
        existing = self._graph_event_by_id(raw_event_id)
        if existing is not None:
            parsed = _stored_graph_commit(existing, adapter=self._adapter)
            if (
                parsed.event_type != HARNESS_GRAPH_INITIALIZED_EVENT_TYPE
                or parsed.graph != graph
                or parsed.run_spec_checksum != run_spec_ref
                or not isinstance(parsed.commit, HarnessGraphProjectionCommit)
                or parsed.commit.state.projection_checksum != state.projection_checksum
            ):
                raise EventReplayMismatchError(
                    sequence=parsed.commit.sequence,
                    reason="graph initialization conflicts with committed run identity",
                )
            return parsed.commit

        recovery, canonical_head = self._recover_graph_snapshot(state.run_id)
        _require_graph_stream_head(recovery, expected_last_sequence)
        if recovery.state is not None:
            raise EventReplayMismatchError(
                sequence=recovery.expected_last_sequence,
                reason="graph initialization attempted after state already exists",
            )
        if canonical_head != 0:
            raise EventReplayMismatchError(
                sequence=canonical_head,
                reason="graph initialization requires an empty canonical run stream",
            )
        if state.last_event_sequence != 1:
            raise HarnessValidationError(
                "initial graph state must project the graph-created sequence",
                code="graph_initial_sequence_mismatch",
            )
        if (
            state.graph_ref.checksum != graph.checksum
            or state.metadata.get("run_spec_checksum") != run_spec_ref
        ):
            raise EventReplayMismatchError(
                sequence=0,
                reason="initial graph state does not match its pinned identity",
            )
        commit = HarnessGraphProjectionCommit(
            HarnessGraphCommitKind.INITIALIZE,
            graph.checksum,
            None,
            state,
            1,
            occurred_at,
        )
        return self._publish_graph_commit(
            run_id=state.run_id,
            event_type=HARNESS_GRAPH_INITIALIZED_EVENT_TYPE,
            commit=commit,
            canonical_head=canonical_head,
            raw_event_id=raw_event_id,
            graph=graph,
            run_spec_checksum=run_spec_ref,
        )

    def commit_graph_decision(
        self,
        decision: HarnessGraphDecision,
        *,
        occurred_at: datetime,
        expected_last_sequence: int,
        activity_input_ref: str | None = None,
        accepted_evidence_refs: tuple[str, ...] = (),
        side_effect_outcome_ref: str | None = None,
    ) -> HarnessGraphDecisionCommit:
        if not isinstance(decision, HarnessGraphDecision):
            raise TypeError("decision must be HarnessGraphDecision")
        raw_event_id = _graph_decision_event_id(decision.decision_checksum)
        existing = self._graph_event_by_id(raw_event_id)
        if existing is not None:
            parsed = _stored_graph_commit(existing, adapter=self._adapter)
            normalized = HarnessGraphDecisionCommit(
                decision,
                parsed.commit.sequence,
                parsed.commit.occurred_at,
                activity_input_ref=activity_input_ref,
                accepted_evidence_refs=accepted_evidence_refs,
                side_effect_outcome_ref=side_effect_outcome_ref,
            )
            if (
                parsed.event_type != HARNESS_GRAPH_DECISION_EVENT_TYPE
                or not isinstance(parsed.commit, HarnessGraphDecisionCommit)
                or parsed.commit != normalized
            ):
                raise EventStoreCorruptionError(
                    "graph decision checksum resolves conflicting content"
                )
            return parsed.commit

        recovery, canonical_head = self._recover_graph_snapshot(decision.run_id)
        _require_graph_stream_head(recovery, expected_last_sequence)
        graph, state = _require_initialized_graph(recovery)
        _validate_graph_decision_storage_identity(graph, state, decision)
        if state.projection_checksum != decision.input_projection_checksum:
            raise EventReplayMismatchError(
                sequence=recovery.expected_last_sequence,
                reason="graph decision attempted from a stale projection",
            )
        _require_no_pending_graph_cause(recovery)
        commit = HarnessGraphDecisionCommit(
            decision,
            recovery.expected_last_sequence + 1,
            occurred_at,
            activity_input_ref=activity_input_ref,
            accepted_evidence_refs=accepted_evidence_refs,
            side_effect_outcome_ref=side_effect_outcome_ref,
        )
        return self._publish_graph_commit(
            run_id=decision.run_id,
            event_type=HARNESS_GRAPH_DECISION_EVENT_TYPE,
            commit=commit,
            canonical_head=canonical_head,
            raw_event_id=raw_event_id,
        )

    def commit_graph_projection(
        self,
        commit: HarnessGraphProjectionCommit,
        *,
        expected_last_sequence: int,
    ) -> HarnessGraphProjectionCommit:
        if not isinstance(commit, HarnessGraphProjectionCommit):
            raise TypeError("commit must be HarnessGraphProjectionCommit")
        if commit.commit_kind is HarnessGraphCommitKind.INITIALIZE:
            raise HarnessValidationError(
                "graph initialization must use initialize_graph",
                code="invalid_graph_projection_commit_kind",
            )
        raw_event_id = _graph_projection_event_id(commit)
        existing = self._graph_event_by_id(raw_event_id)
        if existing is not None:
            parsed = _stored_graph_commit(existing, adapter=self._adapter)
            if (
                parsed.event_type != HARNESS_GRAPH_PROJECTION_EVENT_TYPE
                or not _graph_projection_commit_matches(parsed.commit, commit)
            ):
                raise EventStoreCorruptionError(
                    "graph projection cause resolves conflicting content"
                )
            return parsed.commit

        recovery, canonical_head = self._recover_graph_snapshot(commit.state.run_id)
        _require_graph_stream_head(recovery, expected_last_sequence)
        _validate_graph_projection_candidate(recovery, commit)
        return self._publish_graph_commit(
            run_id=commit.state.run_id,
            event_type=HARNESS_GRAPH_PROJECTION_EVENT_TYPE,
            commit=commit,
            canonical_head=canonical_head,
            raw_event_id=raw_event_id,
        )

    def commit_graph_activity_result(
        self,
        result: HarnessGraphActivityResult,
        *,
        occurred_at: datetime,
        expected_last_sequence: int,
    ) -> HarnessGraphActivityResultCommit:
        if not isinstance(result, HarnessGraphActivityResult):
            raise TypeError("result must be HarnessGraphActivityResult")
        raw_event_id = _graph_activity_result_event_id(result.activity_id)
        existing = self._graph_event_by_id(raw_event_id)
        if existing is not None:
            parsed = _stored_graph_commit(existing, adapter=self._adapter)
            if (
                parsed.event_type != HARNESS_GRAPH_ACTIVITY_RESULT_EVENT_TYPE
                or not isinstance(parsed.commit, HarnessGraphActivityResultCommit)
                or parsed.commit.result != result
            ):
                sequence = (
                    parsed.commit.sequence
                    if isinstance(parsed.commit, HarnessGraphActivityResultCommit)
                    else 0
                )
                raise EventReplayMismatchError(
                    sequence=sequence,
                    reason="graph activity produced a conflicting duplicate result",
                )
            return parsed.commit

        activity = self.activity_for(result.activity_id)
        if activity is None:
            raise HarnessValidationError(
                "graph activity identity is unknown or ambiguous",
                code="graph_activity_identity_mismatch",
            )
        recovery, canonical_head = self._recover_graph_snapshot(activity.run_id)
        _require_graph_stream_head(recovery, expected_last_sequence)
        _, state = _require_initialized_graph(recovery)
        validate_graph_activity_result(activity, result)
        if not any(
            item.activity_id == activity.activity_id for item in state.active_activities
        ):
            raise EventReplayMismatchError(
                sequence=recovery.expected_last_sequence,
                reason="graph activity result is stale or already projected",
            )
        _require_no_pending_graph_cause(recovery)
        commit = HarnessGraphActivityResultCommit(
            result,
            recovery.expected_last_sequence + 1,
            occurred_at,
        )
        return self._publish_graph_commit(
            run_id=activity.run_id,
            event_type=HARNESS_GRAPH_ACTIVITY_RESULT_EVENT_TYPE,
            commit=commit,
            canonical_head=canonical_head,
            raw_event_id=raw_event_id,
        )

    def commit_graph_observation(
        self,
        observation: HarnessAcceptedGraphObservation,
        *,
        occurred_at: datetime,
        expected_last_sequence: int,
    ) -> HarnessGraphObservationCommit:
        if not isinstance(observation, HarnessAcceptedGraphObservation):
            raise TypeError("observation must be HarnessAcceptedGraphObservation")
        raw_event_id = _graph_observation_event_id(observation.observation_checksum)
        existing = self._graph_event_by_id(raw_event_id)
        if existing is not None:
            parsed = _stored_graph_commit(existing, adapter=self._adapter)
            if (
                parsed.event_type != HARNESS_GRAPH_OBSERVATION_EVENT_TYPE
                or not isinstance(parsed.commit, HarnessGraphObservationCommit)
                or parsed.commit.observation != observation
            ):
                raise EventStoreCorruptionError(
                    "graph observation checksum resolves conflicting content"
                )
            return parsed.commit

        if observation.observation_type is HarnessGraphObservationType.RUN_OPERATION:
            run_id = observation.node_instance_id
        else:
            node_event = self._graph_event_by_id(
                _graph_node_event_id(observation.node_instance_id)
            )
            if node_event is None:
                raise HarnessValidationError(
                    "graph node instance identity is unknown or ambiguous",
                    code="graph_observation_node_identity_mismatch",
                )
            parsed_node = _stored_graph_commit(node_event, adapter=self._adapter)
            if not isinstance(
                parsed_node.commit,
                (HarnessGraphProjectionCommit, _HarnessGraphProjectionRecord),
            ):
                raise EventStoreCorruptionError(
                    "graph node index does not reference an activation projection"
                )
            run_id = _graph_commit_run_id(parsed_node.commit)
            if run_id is None:
                raise EventStoreCorruptionError(
                    "graph node index does not reference a run"
                )
        recovery, canonical_head = self._recover_graph_snapshot(run_id)
        _require_graph_stream_head(recovery, expected_last_sequence)
        _, state = _require_initialized_graph(recovery)
        if observation.event_sequence != recovery.expected_last_sequence + 1:
            raise EventReplayMismatchError(
                sequence=recovery.expected_last_sequence,
                reason="graph observation sequence is not contiguous",
            )
        if observation.observation_type is not HarnessGraphObservationType.RUN_OPERATION:
            node = next(
                (
                    item
                    for item in state.node_instances
                    if item.instance_id == observation.node_instance_id
                ),
                None,
            )
            if (
                node is None
                or node.identity.node_id != observation.node_id
                or node.attempt != observation.attempt
            ):
                raise EventReplayMismatchError(
                    sequence=recovery.expected_last_sequence,
                    reason="graph observation does not match the current node attempt",
                )
        _require_no_pending_graph_cause(recovery)
        commit = HarnessGraphObservationCommit(
            observation,
            recovery.expected_last_sequence + 1,
            occurred_at,
        )
        return self._publish_graph_commit(
            run_id=run_id,
            event_type=HARNESS_GRAPH_OBSERVATION_EVENT_TYPE,
            commit=commit,
            canonical_head=canonical_head,
            raw_event_id=raw_event_id,
        )

    def recover_graph(self, run_id: str) -> HarnessGraphRecovery:
        recovery, _ = self._recover_graph_snapshot(run_id)
        return recovery

    def activity_for(self, activity_id: str) -> HarnessGraphActivity | None:
        normalized = _graph_required_text(activity_id, "activity_id")
        event = self._graph_event_by_id(_graph_activity_event_id(normalized))
        if event is None:
            return None
        parsed = _stored_graph_commit(event, adapter=self._adapter)
        commit = parsed.commit
        if (
            parsed.event_type != HARNESS_GRAPH_PROJECTION_EVENT_TYPE
            or commit.activity is None
            or commit.activity.activity_id != normalized
        ):
            raise EventStoreCorruptionError(
                "graph activity index does not reference its durable descriptor"
            )
        return commit.activity

    def mark_activity_dispatched(self, activity_id: str) -> None:
        # Physical dispatch is evidenced by the canonical worker call/result
        # records. Until one exists, recovery deliberately redelivers the
        # already committed descriptor instead of trusting process-local state.
        if self.activity_for(activity_id) is None:
            raise HarnessValidationError(
                "graph activity identity is unknown or ambiguous",
                code="graph_activity_identity_mismatch",
            )

    def _recover_graph_snapshot(
        self,
        run_id: str,
    ) -> tuple[HarnessGraphRecovery, int]:
        safe_run_id = validate_artifact_path_segment(run_id, field="run_id")
        reader = self._require_reader()
        stream_id = f"run:{safe_run_id}"
        canonical_head = (
            reader.get_stream_high_watermark(
                stream_id,
                tenant_id=self._adapter.tenant_id,
            )
            or 0
        )
        with self._graph_snapshot_lock:
            recovery = self._graph_snapshots.get(safe_run_id)
            if recovery is None:
                recovery = HarnessGraphRecovery(safe_run_id, None, None, None, 0)
            if canonical_head < recovery.expected_last_sequence:
                self._graph_snapshots.pop(safe_run_id, None)
                raise EventStoreCorruptionError(
                    "canonical Harness graph stream moved behind its validated snapshot"
                )
            if canonical_head == recovery.expected_last_sequence:
                self._graph_snapshots[safe_run_id] = recovery
                return recovery, canonical_head
            events = _read_canonical_stream(
                reader,
                stream_id=stream_id,
                through_sequence=canonical_head,
                tenant_id=self._adapter.tenant_id,
                data_schemas=frozenset(),
                after_sequence=recovery.expected_last_sequence,
            )
            if not events or events[-1].stream_sequence != canonical_head:
                self._graph_snapshots.pop(safe_run_id, None)
                raise EventStoreCorruptionError(
                    "canonical Harness graph stream suffix is incomplete"
                )
            recovery = _extend_graph_recovery(
                recovery,
                events,
                adapter=self._adapter,
            )
            self._graph_snapshots[safe_run_id] = recovery
            return recovery, canonical_head

    def _on_canonical_event_committed(self, event: StoredEvent) -> None:
        run_id = event.business_context.run_id
        if run_id is None:
            return
        with self._graph_snapshot_lock:
            recovery = self._graph_snapshots.get(run_id)
            if recovery is None or event.stream_sequence <= recovery.expected_last_sequence:
                return
            if event.stream_sequence != recovery.expected_last_sequence + 1:
                self._graph_snapshots.pop(run_id, None)
                return
            try:
                self._graph_snapshots[run_id] = _extend_graph_recovery(
                    recovery,
                    (event,),
                    adapter=self._adapter,
                    validate_replay=False,
                )
            except (EventIncompleteHistoryError, EventStoreCorruptionError):
                # The canonical record is already authoritative. Drop only the
                # process-local acceleration so the next read revalidates it.
                self._graph_snapshots.pop(run_id, None)

    def graph_scope_metadata(self) -> Mapping[str, str]:
        identity_scope_ref = self._adapter.identity_scope_ref
        return (
            {}
            if identity_scope_ref is None
            else {"identity_scope_ref": identity_scope_ref}
        )

    def _graph_event_by_id(self, raw_event_id: str) -> StoredEvent | None:
        return self._require_reader().get_event(
            _scoped_harness_event_id(
                raw_event_id,
                identity_scope_ref=self._adapter.identity_scope_ref,
            ),
            tenant_id=self._adapter.tenant_id,
        )

    def _publish_graph_commit(
        self,
        *,
        run_id: str,
        event_type: str,
        commit: HarnessGraphDecisionCommit
        | HarnessGraphProjectionCommit
        | HarnessGraphActivityResultCommit
        | HarnessGraphObservationCommit,
        canonical_head: int,
        raw_event_id: str,
        graph: NormalizedHarnessGraph | None = None,
        run_spec_checksum: str | None = None,
    ):
        request = _graph_publish_request(
            adapter=self._adapter,
            run_id=run_id,
            event_type=event_type,
            commit=commit,
            raw_event_id=raw_event_id,
            graph=graph,
            run_spec_checksum=run_spec_checksum,
        )
        stored = self._runtime.publish(
            request,
            expected_last_sequence=canonical_head,
        )
        _validate_commit_result(stored, request)
        parsed = _stored_graph_commit(stored, adapter=self._adapter)
        if event_type == HARNESS_GRAPH_PROJECTION_EVENT_TYPE:
            matches = _graph_projection_commit_matches(parsed.commit, commit)
        else:
            matches = parsed.commit == commit
        if not matches:
            raise EventStoreCorruptionError(
                "canonical graph commit differs from the accepted request"
            )
        self._on_canonical_event_committed(stored)
        return commit


def _graph_publish_request(
    *,
    adapter: HarnessEventCanonicalAdapter,
    run_id: str,
    event_type: str,
    commit: HarnessGraphDecisionCommit
    | HarnessGraphProjectionCommit
    | _HarnessGraphProjectionRecord
    | HarnessGraphActivityResultCommit
    | HarnessGraphObservationCommit,
    raw_event_id: str,
    graph: NormalizedHarnessGraph | None,
    run_spec_checksum: str | None,
) -> EventPublishRequest:
    safe_run_id = validate_artifact_path_segment(run_id, field="run_id")
    if event_type not in HARNESS_GRAPH_EVENT_TYPES:
        raise HarnessValidationError(
            "unsupported Harness graph event type",
            code="unsupported_graph_commit_event",
        )
    projection_record = (
        _HarnessGraphProjectionRecord.from_commit(commit)
        if event_type == HARNESS_GRAPH_PROJECTION_EVENT_TYPE
        else None
    )
    data_schema = (
        HARNESS_GRAPH_PROJECTION_RECORD_SCHEMA
        if projection_record is not None
        else HARNESS_GRAPH_COMMIT_SCHEMA
    )
    payload: dict[str, Any] = {
        "commit": (
            projection_record.to_dict()
            if projection_record is not None
            else commit.to_dict()
        )
    }
    if event_type == HARNESS_GRAPH_INITIALIZED_EVENT_TYPE:
        if graph is None or run_spec_checksum is None:
            raise HarnessValidationError(
                "graph initialization event requires pinned graph identity",
                code="graph_initialization_identity_missing",
            )
        payload.update(
            {
                "graph": graph.to_dict(),
                "run_spec_checksum": _graph_checksum(
                    run_spec_checksum,
                    "run_spec_checksum",
                ),
            }
        )
    elif graph is not None or run_spec_checksum is not None:
        raise HarnessValidationError(
            "only graph initialization may carry pinned graph content",
            code="graph_commit_identity_mismatch",
        )
    return EventPublishRequest(
        event_id=_scoped_harness_event_id(
            raw_event_id,
            identity_scope_ref=adapter.identity_scope_ref,
        ),
        event_type=event_type,
        data_schema=data_schema,
        source=HARNESS_EVENT_SOURCE,
        subject=_graph_commit_subject(commit, safe_run_id),
        occurred_at=commit.occurred_at,
        stream_id=f"run:{safe_run_id}",
        correlation_id=safe_run_id,
        business_context=BusinessContext(run_id=safe_run_id),
        producer=adapter.producer,
        tenant_id=adapter.tenant_id,
        security_classification=adapter.security_classification,
        payload=payload,
        extensions={
            DETERMINISTIC_HISTORY_EXTENSION: harness_graph_history(
                data_schema=data_schema,
            ).to_dict()
        },
    )


def _stored_graph_commit(
    event: StoredEvent,
    *,
    adapter: HarnessEventCanonicalAdapter,
) -> _StoredHarnessGraphCommit:
    if not isinstance(event, StoredEvent):
        raise TypeError("event must be StoredEvent")
    event.verify_integrity()
    run_id = event.business_context.run_id
    if (
        event.event_type not in HARNESS_GRAPH_EVENT_TYPES
        or not _graph_event_schema_allowed(event.event_type, event.data_schema)
        or event.source != HARNESS_EVENT_SOURCE
        or run_id is None
        or event.stream_id != f"run:{run_id}"
        or event.correlation_id != run_id
        or event.tenant_id != adapter.tenant_id
        or event.producer != adapter.producer
        or event.security_classification is not adapter.security_classification
        or event.payload is None
        or event.payload_ref is not None
    ):
        raise EventStoreCorruptionError(
            "canonical Harness graph event envelope is invalid"
        )
    payload = thaw_canonical_json(event.payload)
    if not isinstance(payload, Mapping):
        raise EventStoreCorruptionError(
            "canonical Harness graph event payload is invalid"
        )
    graph = None
    run_spec_checksum = None
    if event.event_type == HARNESS_GRAPH_INITIALIZED_EVENT_TYPE:
        _graph_exact_keys(
            payload,
            {"commit", "graph", "run_spec_checksum"},
            "graph initialization event",
        )
        graph_value = _graph_mapping(payload["graph"], "graph")
        graph = NormalizedHarnessGraph.from_dict(graph_value)
        run_spec_checksum = _graph_checksum(
            payload["run_spec_checksum"],
            "run_spec_checksum",
        )
        commit = _graph_projection_commit_from_dict(
            _graph_mapping(payload["commit"], "commit")
        )
        if commit.commit_kind is not HarnessGraphCommitKind.INITIALIZE:
            raise EventStoreCorruptionError(
                "graph initialization event contains another commit kind"
            )
        raw_event_id = _graph_initial_event_id(run_id, graph.checksum)
    else:
        _graph_exact_keys(payload, {"commit"}, "graph commit event")
        commit_value = _graph_mapping(payload["commit"], "commit")
        if event.event_type == HARNESS_GRAPH_DECISION_EVENT_TYPE:
            commit = _graph_decision_commit_from_dict(commit_value)
            raw_event_id = _graph_decision_event_id(commit.decision.decision_checksum)
        elif event.event_type == HARNESS_GRAPH_PROJECTION_EVENT_TYPE:
            commit = (
                _graph_projection_record_from_dict(commit_value)
                if event.data_schema == HARNESS_GRAPH_PROJECTION_RECORD_SCHEMA
                else _graph_projection_commit_from_dict(commit_value)
            )
            if commit.commit_kind is HarnessGraphCommitKind.INITIALIZE:
                raise EventStoreCorruptionError(
                    "graph projection event contains initialization"
                )
            raw_event_id = _graph_projection_event_id(commit)
        elif event.event_type == HARNESS_GRAPH_ACTIVITY_RESULT_EVENT_TYPE:
            commit = _graph_activity_result_commit_from_dict(commit_value)
            raw_event_id = _graph_activity_result_event_id(commit.result.activity_id)
        else:
            commit = _graph_observation_commit_from_dict(commit_value)
            raw_event_id = _graph_observation_event_id(
                commit.observation.observation_checksum
            )
    expected_event_id = _scoped_harness_event_id(
        raw_event_id,
        identity_scope_ref=adapter.identity_scope_ref,
    )
    if (
        event.event_id != expected_event_id
        or event.occurred_at != commit.occurred_at
        or event.subject != _graph_commit_subject(commit, run_id)
        or event.stream_sequence != commit.sequence
    ):
        raise EventStoreCorruptionError(
            "canonical Harness graph event identity conflicts with its commit"
        )
    commit_run_id = _graph_commit_run_id(commit)
    if commit_run_id is not None and commit_run_id != run_id:
        raise EventStoreCorruptionError(
            "canonical Harness graph commit belongs to another run"
        )
    return _StoredHarnessGraphCommit(
        event.event_type,
        commit,
        graph=graph,
        run_spec_checksum=run_spec_checksum,
    )


def _graph_event_schema_allowed(event_type: str, data_schema: str) -> bool:
    if event_type == HARNESS_GRAPH_PROJECTION_EVENT_TYPE:
        return data_schema in {
            HARNESS_GRAPH_COMMIT_SCHEMA,
            HARNESS_GRAPH_PROJECTION_RECORD_SCHEMA,
        }
    return data_schema == HARNESS_GRAPH_COMMIT_SCHEMA


def _graph_projection_commit_matches(
    stored: HarnessGraphProjectionCommit | _HarnessGraphProjectionRecord,
    expected: HarnessGraphProjectionCommit,
) -> bool:
    if not isinstance(expected, HarnessGraphProjectionCommit):
        return False
    if isinstance(stored, HarnessGraphProjectionCommit):
        return stored == expected
    if isinstance(stored, _HarnessGraphProjectionRecord):
        return stored == _HarnessGraphProjectionRecord.from_commit(expected)
    return False


def _graph_decision_commit_from_dict(
    value: Mapping[str, Any],
) -> HarnessGraphDecisionCommit:
    _graph_exact_keys(
        value,
        {
            "schema_version",
            "commit_kind",
            "decision",
            "sequence",
            "occurred_at",
            "activity_input_ref",
            "accepted_evidence_refs",
            "side_effect_outcome_ref",
            "commit_checksum",
        },
        "graph decision commit",
    )
    if value["commit_kind"] != HarnessGraphCommitKind.DECISION.value:
        raise EventStoreCorruptionError("graph decision commit kind is invalid")
    try:
        commit = HarnessGraphDecisionCommit(
            decision=HarnessGraphDecision.from_dict(
                _graph_mapping(value["decision"], "decision")
            ),
            sequence=value["sequence"],
            occurred_at=parse_datetime(value["occurred_at"]),
            activity_input_ref=value["activity_input_ref"],
            accepted_evidence_refs=tuple(
                _graph_array(
                    value["accepted_evidence_refs"],
                    "accepted_evidence_refs",
                )
            ),
            side_effect_outcome_ref=value["side_effect_outcome_ref"],
            schema_version=value["schema_version"],
        )
    except (HarnessValidationError, TypeError, ValueError) as exc:
        raise EventStoreCorruptionError(
            "canonical graph decision commit violates its typed contract"
        ) from exc
    _validate_graph_commit_checksum(value, commit.commit_checksum)
    return commit


def _graph_projection_commit_from_dict(
    value: Mapping[str, Any],
) -> HarnessGraphProjectionCommit:
    _graph_exact_keys(
        value,
        {
            "schema_version",
            "commit_kind",
            "cause_checksum",
            "previous_projection_checksum",
            "state",
            "sequence",
            "occurred_at",
            "budget_reservations",
            "budget_consumptions",
            "activity",
            "commit_checksum",
        },
        "graph projection commit",
    )
    activity_value = value["activity"]
    commit = HarnessGraphProjectionCommit(
        commit_kind=value["commit_kind"],
        cause_checksum=value["cause_checksum"],
        previous_projection_checksum=value["previous_projection_checksum"],
        state=HarnessGraphState.from_dict(_graph_mapping(value["state"], "state")),
        sequence=value["sequence"],
        occurred_at=parse_datetime(value["occurred_at"]),
        budget_reservations=_graph_mapping(
            value["budget_reservations"],
            "budget_reservations",
        ),
        budget_consumptions=_graph_mapping(
            value["budget_consumptions"],
            "budget_consumptions",
        ),
        activity=(
            None
            if activity_value is None
            else _graph_activity_from_dict(_graph_mapping(activity_value, "activity"))
        ),
        schema_version=value["schema_version"],
    )
    _validate_graph_commit_checksum(value, commit.commit_checksum)
    return commit


def _graph_projection_record_from_dict(
    value: Mapping[str, Any],
) -> _HarnessGraphProjectionRecord:
    _graph_exact_keys(
        value,
        {
            "schema_version",
            "state_schema_version",
            "reducer_version",
            "commit_kind",
            "run_id",
            "cause_checksum",
            "previous_projection_checksum",
            "projection_checksum",
            "sequence",
            "occurred_at",
            "budget_reservations",
            "budget_consumptions",
            "activity",
            "state_summary",
            "activated_node_instance_id",
            "projection_commit_checksum",
            "record_checksum",
        },
        "graph projection record",
    )
    activity_value = value["activity"]
    try:
        record = _HarnessGraphProjectionRecord(
            commit_kind=value["commit_kind"],
            run_id=value["run_id"],
            cause_checksum=value["cause_checksum"],
            previous_projection_checksum=value["previous_projection_checksum"],
            projection_checksum=value["projection_checksum"],
            sequence=value["sequence"],
            occurred_at=parse_datetime(value["occurred_at"]),
            budget_reservations=_graph_mapping(
                value["budget_reservations"],
                "budget_reservations",
            ),
            budget_consumptions=_graph_mapping(
                value["budget_consumptions"],
                "budget_consumptions",
            ),
            activity=(
                None
                if activity_value is None
                else _graph_activity_from_dict(
                    _graph_mapping(activity_value, "activity")
                )
            ),
            state_summary=_graph_mapping(value["state_summary"], "state_summary"),
            activated_node_instance_id=value["activated_node_instance_id"],
            projection_commit_checksum=value["projection_commit_checksum"],
            state_schema_version=value["state_schema_version"],
            reducer_version=value["reducer_version"],
            schema_version=value["schema_version"],
        )
    except (HarnessValidationError, TypeError, ValueError) as exc:
        raise EventStoreCorruptionError(
            "canonical graph projection record violates its typed contract"
        ) from exc
    supplied = value["record_checksum"]
    if supplied != record.record_checksum:
        raise EventStoreCorruptionError(
            "canonical graph projection record checksum does not match"
        )
    return record


def _graph_activity_result_commit_from_dict(
    value: Mapping[str, Any],
) -> HarnessGraphActivityResultCommit:
    _graph_exact_keys(
        value,
        {
            "schema_version",
            "commit_kind",
            "result",
            "sequence",
            "occurred_at",
            "commit_checksum",
        },
        "graph activity result commit",
    )
    if value["commit_kind"] != HarnessGraphCommitKind.ACTIVITY_RESULT.value:
        raise EventStoreCorruptionError("graph activity result commit kind is invalid")
    commit = HarnessGraphActivityResultCommit(
        result=_graph_activity_result_from_dict(
            _graph_mapping(value["result"], "result")
        ),
        sequence=value["sequence"],
        occurred_at=parse_datetime(value["occurred_at"]),
        schema_version=value["schema_version"],
    )
    _validate_graph_commit_checksum(value, commit.commit_checksum)
    return commit


def _graph_observation_commit_from_dict(
    value: Mapping[str, Any],
) -> HarnessGraphObservationCommit:
    _graph_exact_keys(
        value,
        {
            "schema_version",
            "commit_kind",
            "observation",
            "sequence",
            "occurred_at",
            "commit_checksum",
        },
        "graph observation commit",
    )
    if value["commit_kind"] != HarnessGraphCommitKind.OBSERVATION.value:
        raise EventStoreCorruptionError("graph observation commit kind is invalid")
    commit = HarnessGraphObservationCommit(
        observation=_graph_observation_from_dict(
            _graph_mapping(value["observation"], "observation")
        ),
        sequence=value["sequence"],
        occurred_at=parse_datetime(value["occurred_at"]),
        schema_version=value["schema_version"],
    )
    _validate_graph_commit_checksum(value, commit.commit_checksum)
    return commit


def _graph_activity_from_dict(value: Mapping[str, Any]) -> HarnessGraphActivity:
    try:
        return HarnessGraphActivity.from_dict(value)
    except (HarnessValidationError, TypeError, ValueError) as exc:
        raise EventStoreCorruptionError(
            "graph activity contract or deterministic identity is invalid"
        ) from exc


def _graph_activity_result_from_dict(
    value: Mapping[str, Any],
) -> HarnessGraphActivityResult:
    legacy_fields = {
        "schema_version",
        "activity_id",
        "node_instance_id",
        "attempt",
        "idempotency_key",
        "fencing_generation",
        "activity_ref",
        "evidence_ref",
        "payload_ref",
        "status",
        "termination_confirmed",
        "tenant_scope_ref",
        "identity_scope_ref",
        "subject_scope_ref",
        "result_checksum",
    }
    actual_fields = set(value)
    allowed_fields = {
        frozenset(legacy_fields),
        frozenset((*legacy_fields, "result_lineage")),
    }
    if actual_fields not in allowed_fields:
        raise EventStoreCorruptionError("graph activity result fields are invalid")
    try:
        lineage = (
            HarnessGraphResultLineage.from_dict(
                _graph_mapping(value["result_lineage"], "result lineage")
            )
            if "result_lineage" in value
            else None
        )
        result = HarnessGraphActivityResult(
            activity_id=value["activity_id"],
            node_instance_id=value["node_instance_id"],
            attempt=value["attempt"],
            idempotency_key=value["idempotency_key"],
            fencing_generation=value["fencing_generation"],
            activity_ref=_graph_contract_reference(
                value["activity_ref"],
                "activity_ref",
            ),
            evidence_ref=value["evidence_ref"],
            payload_ref=value["payload_ref"],
            status=value["status"],
            termination_confirmed=value["termination_confirmed"],
            tenant_scope_ref=value["tenant_scope_ref"],
            identity_scope_ref=value["identity_scope_ref"],
            subject_scope_ref=value["subject_scope_ref"],
            result_lineage=lineage,
            schema_version=value["schema_version"],
        )
    except (HarnessValidationError, TypeError, ValueError) as exc:
        raise EventStoreCorruptionError(
            "graph activity result violates its typed contract"
        ) from exc
    if value["result_checksum"] != result.result_checksum:
        raise EventStoreCorruptionError("graph activity result checksum is invalid")
    return result


def _graph_observation_from_dict(
    value: Mapping[str, Any],
) -> HarnessAcceptedGraphObservation:
    _graph_exact_keys(
        value,
        {
            "observation_type",
            "node_id",
            "node_instance_id",
            "attempt",
            "event_sequence",
            "contract_ref",
            "evidence_ref",
            "payload",
            "control_fact_paths",
            "payload_ref",
            "observation_checksum",
        },
        "graph observation",
    )
    observation = HarnessAcceptedGraphObservation(
        observation_type=value["observation_type"],
        node_id=value["node_id"],
        node_instance_id=value["node_instance_id"],
        attempt=value["attempt"],
        event_sequence=value["event_sequence"],
        contract_ref=_graph_contract_reference(
            value["contract_ref"],
            "contract_ref",
        ),
        evidence_ref=value["evidence_ref"],
        payload=_graph_mapping(value["payload"], "payload"),
        control_fact_paths=tuple(
            _graph_array(value["control_fact_paths"], "control_fact_paths")
        ),
    )
    if (
        value["payload_ref"] != observation.payload_ref
        or value["observation_checksum"] != observation.observation_checksum
    ):
        raise EventStoreCorruptionError("graph observation checksum is invalid")
    return observation


def _graph_state_reference(value: Any):
    from framework.harness.control_plane.graph_state import HarnessGraphReference

    return HarnessGraphReference.from_dict(_graph_mapping(value, "graph_ref"))


def _graph_contract_reference(
    value: Any,
    field_name: str,
) -> HarnessContractReference:
    return HarnessContractReference.from_dict(_graph_mapping(value, field_name))


def _validate_graph_projection_candidate(
    recovery: HarnessGraphRecovery,
    commit: HarnessGraphProjectionCommit,
) -> None:
    graph, state = _require_initialized_graph(recovery)
    if commit.sequence != recovery.expected_last_sequence + 1:
        raise EventReplayMismatchError(
            sequence=recovery.expected_last_sequence,
            reason="graph projection sequence is not contiguous",
        )
    if commit.previous_projection_checksum != state.projection_checksum:
        raise EventReplayMismatchError(
            sequence=recovery.expected_last_sequence,
            reason="graph projection attempted from a stale state",
        )
    if (
        commit.state.run_id != state.run_id
        or commit.state.graph_ref != state.graph_ref
        or commit.state.graph_ref.checksum != graph.checksum
    ):
        raise EventStoreCorruptionError(
            "graph projection state is outside the initialized run"
        )
    pending: tuple[
        HarnessGraphDecisionCommit
        | HarnessGraphActivityResultCommit
        | HarnessGraphObservationCommit,
        ...,
    ] = (
        *recovery.pending_decisions,
        *recovery.pending_activity_results,
        *recovery.pending_observations,
    )
    if len(pending) != 1:
        raise EventStoreCorruptionError(
            "graph projection requires exactly one committed causal record"
        )
    cause = pending[0]
    expected_kind: HarnessGraphCommitKind
    expected_checksum: str
    if isinstance(cause, HarnessGraphDecisionCommit):
        expected_kind = HarnessGraphCommitKind.DECISION_PROJECTION
        expected_checksum = cause.decision.decision_checksum
    elif isinstance(cause, HarnessGraphActivityResultCommit):
        expected_kind = HarnessGraphCommitKind.ACTIVITY_RESULT_PROJECTION
        expected_checksum = cause.result.result_checksum
    else:
        expected_kind = HarnessGraphCommitKind.OBSERVATION_PROJECTION
        expected_checksum = cause.observation.observation_checksum
    if (
        commit.commit_kind is not expected_kind
        or commit.cause_checksum != expected_checksum
        or commit.sequence != cause.sequence + 1
    ):
        raise EventStoreCorruptionError(
            "graph projection kind does not match its committed cause"
        )
    if commit.activity is not None:
        if not isinstance(cause, HarnessGraphDecisionCommit):
            raise EventStoreCorruptionError(
                "graph activity has no causal decision commit"
            )
        if cause.activity_input_ref != commit.activity.input_ref:
            raise EventStoreCorruptionError(
                "graph activity input does not match its decision commit"
            )
        _validate_graph_activity_binding(commit.activity, cause, commit.state)


def _require_initialized_graph(
    recovery: HarnessGraphRecovery,
) -> tuple[NormalizedHarnessGraph, HarnessGraphState]:
    if recovery.graph is None or recovery.state is None:
        raise EventReplayMismatchError(
            sequence=recovery.expected_last_sequence,
            reason="graph run has not been durably initialized",
        )
    return recovery.graph, recovery.state


def _validate_graph_adapter_scope(
    state: HarnessGraphState,
    adapter: HarnessEventCanonicalAdapter,
    *,
    durable: bool = False,
) -> None:
    actual = state.metadata.get("identity_scope_ref")
    expected = adapter.identity_scope_ref
    if actual == expected:
        return
    if durable:
        raise EventStoreCorruptionError(
            "durable Graph state identity scope conflicts with adapter tenant"
        )
    raise HarnessValidationError(
        "Graph state identity scope conflicts with adapter tenant",
        code="graph_identity_scope_mismatch",
    )


def _validate_graph_projection_replay(recovery: HarnessGraphRecovery) -> None:
    from framework.harness.control_plane.graph_application import (
        HarnessGraphDecisionApplier,
    )

    graph, state = _require_initialized_graph(recovery)
    applier = HarnessGraphDecisionApplier()
    decisions = {
        item.decision.decision_checksum: item for item in recovery.decision_commits
    }
    results = {
        item.result.result_checksum: item for item in recovery.activity_result_commits
    }
    observations = {
        item.observation.observation_checksum: item
        for item in recovery.observation_commits
    }
    activities = {item.activity_id: item for item in recovery.activities}
    projections = recovery.projection_commits
    previous = projections[0].state
    try:
        for projection in projections[1:]:
            if projection.commit_kind is HarnessGraphCommitKind.DECISION_PROJECTION:
                cause = decisions[projection.cause_checksum]
                applied = applier.apply(
                    previous,
                    graph,
                    cause.decision,
                    decision_sequence=cause.sequence,
                    projection_sequence=projection.sequence,
                    activity_input_ref=cause.activity_input_ref,
                    accepted_evidence_refs=cause.accepted_evidence_refs,
                    side_effect_outcome_ref=cause.side_effect_outcome_ref,
                )
                if (
                    applied.state != projection.state
                    or applied.budget_reservations != projection.budget_reservations
                    or applied.budget_consumptions != projection.budget_consumptions
                    or applied.activity != projection.activity
                ):
                    raise EventStoreCorruptionError(
                        "durable Graph decision projection differs from pure replay"
                    )
            elif (
                projection.commit_kind
                is HarnessGraphCommitKind.ACTIVITY_RESULT_PROJECTION
            ):
                cause = results[projection.cause_checksum]
                activity = activities[cause.result.activity_id]
                applied_state = applier.apply_activity_result(
                    previous,
                    activity,
                    cause.result,
                    result_sequence=cause.sequence,
                    projection_sequence=projection.sequence,
                )
                if (
                    applied_state != projection.state
                    or projection.budget_reservations
                    or projection.budget_consumptions
                    or projection.activity is not None
                ):
                    raise EventStoreCorruptionError(
                        "durable Graph activity projection differs from pure replay"
                    )
            else:
                cause = observations[projection.cause_checksum]
                applied_state = applier.apply_observation(
                    previous,
                    graph,
                    cause.observation,
                    observation_sequence=cause.sequence,
                    projection_sequence=projection.sequence,
                )
                if (
                    applied_state != projection.state
                    or projection.budget_reservations
                    or projection.budget_consumptions
                    or projection.activity is not None
                ):
                    raise EventStoreCorruptionError(
                        "durable Graph observation projection differs from pure replay"
                    )
            previous = projection.state

        if recovery.pending_decisions:
            cause = recovery.pending_decisions[0]
            applier.apply(
                state,
                graph,
                cause.decision,
                decision_sequence=cause.sequence,
                projection_sequence=cause.sequence + 1,
                activity_input_ref=cause.activity_input_ref,
                accepted_evidence_refs=cause.accepted_evidence_refs,
                side_effect_outcome_ref=cause.side_effect_outcome_ref,
            )
        elif recovery.pending_activity_results:
            cause = recovery.pending_activity_results[0]
            applier.apply_activity_result(
                state,
                activities[cause.result.activity_id],
                cause.result,
                result_sequence=cause.sequence,
                projection_sequence=cause.sequence + 1,
            )
        elif recovery.pending_observations:
            cause = recovery.pending_observations[0]
            applier.apply_observation(
                state,
                graph,
                cause.observation,
                observation_sequence=cause.sequence,
                projection_sequence=cause.sequence + 1,
            )
    except (HarnessValidationError, EventReplayMismatchError, KeyError) as exc:
        raise EventStoreCorruptionError(
            "durable Graph projection cannot be reproduced from canonical history"
        ) from exc


def _require_graph_stream_head(
    recovery: HarnessGraphRecovery,
    expected_last_sequence: int,
) -> None:
    if recovery.expected_last_sequence != expected_last_sequence:
        raise EventReplayMismatchError(
            sequence=recovery.expected_last_sequence,
            reason="graph commit attempted from a stale stream sequence",
        )


def _require_no_pending_graph_cause(recovery: HarnessGraphRecovery) -> None:
    if (
        recovery.pending_decisions
        or recovery.pending_activity_results
        or recovery.pending_observations
    ):
        raise EventReplayMismatchError(
            sequence=recovery.expected_last_sequence,
            reason="graph stream has a committed cause awaiting projection",
        )


def _materialize_graph_projection_record(
    record: _HarnessGraphProjectionRecord,
    *,
    graph: NormalizedHarnessGraph,
    previous_state: HarnessGraphState,
    decisions: list[HarnessGraphDecisionCommit],
    results: list[HarnessGraphActivityResultCommit],
    observations: list[HarnessGraphObservationCommit],
    activities: Mapping[str, HarnessGraphActivity],
) -> HarnessGraphProjectionCommit:
    """Rebuild one compact projection from its durable cause and prior state."""

    from framework.harness.control_plane.graph_application import (
        HarnessGraphDecisionApplier,
    )

    decision_by_checksum = {
        item.decision.decision_checksum: item for item in decisions
    }
    result_by_checksum = {
        item.result.result_checksum: item for item in results
    }
    observation_by_checksum = {
        item.observation.observation_checksum: item for item in observations
    }
    applier = HarnessGraphDecisionApplier()
    try:
        if record.commit_kind is HarnessGraphCommitKind.DECISION_PROJECTION:
            cause = decision_by_checksum[record.cause_checksum]
            applied = applier.apply(
                previous_state,
                graph,
                cause.decision,
                decision_sequence=cause.sequence,
                projection_sequence=record.sequence,
                activity_input_ref=cause.activity_input_ref,
                accepted_evidence_refs=cause.accepted_evidence_refs,
                side_effect_outcome_ref=cause.side_effect_outcome_ref,
            )
            state = applied.state
            reservations = applied.budget_reservations
            consumptions = applied.budget_consumptions
            activity = applied.activity
        elif record.commit_kind is HarnessGraphCommitKind.ACTIVITY_RESULT_PROJECTION:
            cause = result_by_checksum[record.cause_checksum]
            activity_descriptor = activities[cause.result.activity_id]
            state = applier.apply_activity_result(
                previous_state,
                activity_descriptor,
                cause.result,
                result_sequence=cause.sequence,
                projection_sequence=record.sequence,
            )
            reservations = {}
            consumptions = {}
            activity = None
        else:
            cause = observation_by_checksum[record.cause_checksum]
            state = applier.apply_observation(
                previous_state,
                graph,
                cause.observation,
                observation_sequence=cause.sequence,
                projection_sequence=record.sequence,
            )
            reservations = {}
            consumptions = {}
            activity = None
        commit = HarnessGraphProjectionCommit(
            commit_kind=record.commit_kind,
            cause_checksum=record.cause_checksum,
            previous_projection_checksum=record.previous_projection_checksum,
            state=state,
            sequence=record.sequence,
            occurred_at=record.occurred_at,
            budget_reservations=reservations,
            budget_consumptions=consumptions,
            activity=activity,
        )
        expected = _HarnessGraphProjectionRecord.from_commit(commit)
    except (KeyError, HarnessValidationError, EventReplayMismatchError, TypeError, ValueError) as exc:
        raise EventStoreCorruptionError(
            "compact graph projection cannot be reproduced from canonical history"
        ) from exc
    if expected != record:
        raise EventStoreCorruptionError(
            "compact graph projection differs from pure replay"
        )
    return commit


def _extend_graph_recovery(
    recovery: HarnessGraphRecovery,
    events: tuple[StoredEvent, ...],
    *,
    adapter: HarnessEventCanonicalAdapter,
    validate_replay: bool = True,
) -> HarnessGraphRecovery:
    """Apply a canonical suffix once, then validate one immutable snapshot.

    Durable graph writes are commonly interleaved with phase, gate, and worker
    marker events.  Keeping the already parsed graph commits avoids reparsing
    the complete run stream after every one of those records while preserving
    the same full ``HarnessGraphRecovery`` validation at the suffix boundary.
    """

    if not events:
        return recovery
    run_id = recovery.run_id
    graph = recovery.graph
    run_spec_checksum = recovery.run_spec_checksum
    state = recovery.state
    decisions = list(recovery.decision_commits)
    projections = list(recovery.projection_commits)
    results = list(recovery.activity_result_commits)
    observations = list(recovery.observation_commits)
    activities = {item.activity_id: item for item in recovery.activities}
    dispatched = set(recovery.dispatched_activity_ids)
    expected_sequence = recovery.expected_last_sequence

    for event in events:
        if event.stream_id != f"run:{run_id}":
            raise EventStoreCorruptionError(
                "canonical Harness graph suffix belongs to another stream"
            )
        if event.stream_sequence != expected_sequence + 1:
            raise EventStoreCorruptionError(
                "canonical Harness graph suffix has a stream sequence gap"
            )
        if event.event_type in HARNESS_GRAPH_EVENT_TYPES:
            if not _graph_event_schema_allowed(event.event_type, event.data_schema):
                raise EventStoreCorruptionError(
                    "canonical Harness graph event uses an unsupported schema"
                )
            item = _stored_graph_commit(event, adapter=adapter)
            if event.stream_sequence != item.commit.sequence:
                raise EventStoreCorruptionError(
                    "graph commit sequence differs from canonical stream sequence"
                )
            commit = item.commit
            if isinstance(commit, _HarnessGraphProjectionRecord):
                if graph is None or state is None or run_spec_checksum is None:
                    raise EventIncompleteHistoryError(
                        "compact graph projection appears before initialization"
                    )
                commit = _materialize_graph_projection_record(
                    commit,
                    graph=graph,
                    previous_state=state,
                    decisions=decisions,
                    results=results,
                    observations=observations,
                    activities=activities,
                )
            if event.event_type == HARNESS_GRAPH_INITIALIZED_EVENT_TYPE:
                if (
                    graph is not None
                    or decisions
                    or projections
                    or results
                    or observations
                    or item.graph is None
                    or item.run_spec_checksum is None
                    or not isinstance(commit, HarnessGraphProjectionCommit)
                ):
                    raise EventStoreCorruptionError(
                        "graph history requires exactly one initialization event"
                    )
                graph = item.graph
                run_spec_checksum = item.run_spec_checksum
                state = commit.state
                projections.append(commit)
            elif graph is None or state is None or run_spec_checksum is None:
                raise EventIncompleteHistoryError(
                    "canonical run stream contains Graph history before initialization"
                )
            elif isinstance(commit, HarnessGraphDecisionCommit):
                decisions.append(commit)
            elif isinstance(commit, HarnessGraphProjectionCommit):
                projections.append(commit)
                state = commit.state
                if commit.activity is not None:
                    activities[commit.activity.activity_id] = commit.activity
            elif isinstance(commit, HarnessGraphActivityResultCommit):
                results.append(commit)
                dispatched.add(commit.result.activity_id)
            elif isinstance(commit, HarnessGraphObservationCommit):
                observations.append(commit)
            else:  # pragma: no cover - the parser exhausts the union
                raise EventStoreCorruptionError(
                    "canonical Harness graph event has an unknown commit type"
                )
        elif event.data_schema == HARNESS_GRAPH_COMMIT_SCHEMA:
            raise EventStoreCorruptionError(
                "canonical Harness graph schema is bound to an unknown event type"
            )
        elif graph is not None:
            activity_id = _dispatched_graph_activity_id(
                event,
                graph=graph,
                activities=activities,
                adapter=adapter,
            )
            if activity_id is not None:
                dispatched.add(activity_id)
        expected_sequence = event.stream_sequence

    if graph is None or run_spec_checksum is None or state is None:
        raise EventIncompleteHistoryError(
            "canonical run stream contains history without a Graph initialization"
        )
    recovery = HarnessGraphRecovery(
        run_id=run_id,
        graph=graph,
        run_spec_checksum=run_spec_checksum,
        state=state,
        expected_last_sequence=expected_sequence,
        decision_commits=tuple(decisions),
        projection_commits=tuple(projections),
        activity_result_commits=tuple(results),
        observation_commits=tuple(observations),
        activities=tuple(activities.values()),
        dispatched_activity_ids=frozenset(
            dispatched.intersection(activities)
        ),
    )
    _validate_graph_adapter_scope(recovery.state, adapter, durable=True)
    for activity in recovery.activities:
        if activity.identity_scope_ref != adapter.identity_scope_ref:
            raise EventStoreCorruptionError(
                "durable Graph activity identity scope conflicts with adapter tenant"
            )
    if validate_replay:
        _validate_graph_projection_replay(recovery)
    return recovery


def _read_canonical_stream(
    reader: EventReaderPort,
    *,
    stream_id: str,
    through_sequence: int,
    tenant_id: str | None,
    data_schemas: frozenset[str],
    after_sequence: int = 0,
) -> tuple[StoredEvent, ...]:
    cursor = (
        None
        if after_sequence == 0
        else StreamSequenceCursor(
            stream_id=stream_id,
            after_sequence=after_sequence,
            high_watermark=through_sequence,
            tenant_id=tenant_id,
        )
    )
    events: list[StoredEvent] = []
    while True:
        page = reader.read_stream(
            StreamReadRequest(
                stream_id=stream_id,
                cursor=cursor,
                limit=500,
                through_sequence=through_sequence,
                tenant_id=tenant_id,
                data_schemas=data_schemas,
            )
        )
        events.extend(page.events)
        if page.next_cursor is None:
            return tuple(events)
        cursor = page.next_cursor


def _dispatched_graph_activity_id(
    event: StoredEvent,
    *,
    graph: NormalizedHarnessGraph,
    activities: Mapping[str, HarnessGraphActivity],
    adapter: HarnessEventCanonicalAdapter,
) -> str | None:
    if event.event_type == "worker_called":
        payload = thaw_canonical_json(event.payload or {})
        if not isinstance(payload, Mapping):
            raise EventStoreCorruptionError(
                "Graph worker call marker payload is invalid"
            )
        node_instance_id = payload.get("node_instance_id")
        if node_instance_id is None:
            return None
        value = payload.get("activity_id")
        if not isinstance(value, str) or value not in activities:
            raise EventStoreCorruptionError(
                "Graph worker call marker references an unknown activity"
            )
        activity = activities[value]
        expected = _legacy_graph_activity_descriptor(activity, graph)
        try:
            _validate_stored_harness_event(event)
            validate_activity_call_marker(payload, expected_activity=expected)
        except (EventIntegrityError, HarnessValidationError, TypeError) as exc:
            raise EventStoreCorruptionError(
                "Graph worker call marker is invalid"
            ) from exc
        if (
            payload.get("projection_schema") != HARNESS_SAFE_PROJECTION
            or node_instance_id != activity.node_instance_id
            or event.subject != expected.step_id
            or event.correlation_id != expected.run_id
            or event.business_context.run_id != expected.run_id
            or event.business_context.step_id != expected.step_id
            or event.tenant_id != adapter.tenant_id
            or event.security_classification is not adapter.security_classification
            or event.producer != adapter.producer
        ):
            raise EventStoreCorruptionError(
                "Graph worker call marker context conflicts with activity"
            )
    elif event.event_type == "worker_result_recorded":
        extension = thaw_canonical_json(
            event.extensions.get(HARNESS_ACTIVITY_EXTENSION, {})
        )
        activity = extension.get("activity") if isinstance(extension, Mapping) else None
        value = activity.get("activity_id") if isinstance(activity, Mapping) else None
        if isinstance(value, str) and value in activities:
            expected = _legacy_graph_activity_descriptor(activities[value], graph)
            try:
                recorded = HarnessActivity.from_dict(activity)
            except (HarnessValidationError, TypeError, ValueError) as exc:
                raise EventStoreCorruptionError(
                    "Graph worker result marker activity is invalid"
                ) from exc
            if recorded != expected:
                raise EventStoreCorruptionError(
                    "Graph worker result marker conflicts with activity"
                )
    else:
        return None
    if not isinstance(value, str) or not value.startswith("hga_"):
        return None
    return value


def _legacy_graph_activity_descriptor(
    activity: HarnessGraphActivity,
    graph: NormalizedHarnessGraph,
) -> HarnessActivity:
    definition = next(
        (item for item in graph.nodes if item.node_id == activity.node_id),
        None,
    )
    if not isinstance(definition, HarnessExecutableNode):
        raise EventStoreCorruptionError(
            "Graph activity has no executable node definition"
        )
    worker_type = definition.metadata.get("worker_type")
    if not isinstance(worker_type, str) or not worker_type:
        raise EventStoreCorruptionError(
            "Graph executable node has no canonical worker type"
        )
    return HarnessActivity(
        activity_id=activity.activity_id,
        run_id=activity.run_id,
        step_id=definition.step_id,
        attempt=activity.attempt,
        activity_type=worker_type,
        idempotency_key=activity.idempotency_key,
        input_checksum=activity.input_ref,
        identity_scope_ref=activity.identity_scope_ref,
        contract_version=HARNESS_ACTIVITY_CONTRACT,
        worker_version=activity.worker_ref.version,
    )


def _graph_commit_subject(
    commit: HarnessGraphDecisionCommit
    | HarnessGraphProjectionCommit
    | HarnessGraphActivityResultCommit
    | HarnessGraphObservationCommit,
    run_id: str,
) -> str:
    if isinstance(commit, HarnessGraphDecisionCommit):
        return commit.decision.node_instance_id or commit.decision.node_id or run_id
    if isinstance(commit, HarnessGraphActivityResultCommit):
        return commit.result.node_instance_id
    if isinstance(commit, HarnessGraphObservationCommit):
        return commit.observation.node_instance_id
    if commit.activity is not None:
        return commit.activity.node_instance_id
    if isinstance(commit, _HarnessGraphProjectionRecord):
        return commit.activated_node_instance_id or run_id
    activated = _activated_node_for_projection(commit)
    return run_id if activated is None else activated.instance_id


def _graph_commit_run_id(
    commit: HarnessGraphDecisionCommit
    | HarnessGraphProjectionCommit
    | _HarnessGraphProjectionRecord
    | HarnessGraphActivityResultCommit
    | HarnessGraphObservationCommit,
) -> str | None:
    if isinstance(commit, HarnessGraphDecisionCommit):
        return commit.decision.run_id
    if isinstance(commit, HarnessGraphProjectionCommit):
        return commit.state.run_id
    if isinstance(commit, _HarnessGraphProjectionRecord):
        return commit.run_id
    return None


def _graph_initial_event_id(run_id: str, graph_checksum: str) -> str:
    digest = hashlib.sha256(
        f"{run_id}|{_graph_checksum(graph_checksum, 'graph_checksum')}".encode()
    ).hexdigest()
    return f"harness-graph-initialized:{digest}"


def _graph_decision_event_id(decision_checksum: str) -> str:
    return (
        "harness-graph-decision:"
        f"{_graph_checksum_digest(decision_checksum, 'decision_checksum')}"
    )


def _graph_projection_event_id(
    commit: HarnessGraphProjectionCommit | _HarnessGraphProjectionRecord,
) -> str:
    if commit.activity is not None:
        return _graph_activity_event_id(commit.activity.activity_id)
    activated = (
        None
        if isinstance(commit, _HarnessGraphProjectionRecord)
        else _activated_node_for_projection(commit)
    )
    if isinstance(commit, _HarnessGraphProjectionRecord):
        if commit.activated_node_instance_id is not None:
            return _graph_node_event_id(commit.activated_node_instance_id)
    if activated is not None:
        return _graph_node_event_id(activated.instance_id)
    return (
        "harness-graph-projection:"
        f"{_graph_checksum_digest(commit.cause_checksum, 'cause_checksum')}"
    )


def _graph_activity_event_id(activity_id: str) -> str:
    return f"harness-graph-activity:{_graph_required_text(activity_id, 'activity_id')}"


def _graph_node_event_id(node_instance_id: str) -> str:
    return (
        "harness-graph-node:"
        f"{_graph_required_text(node_instance_id, 'node_instance_id')}"
    )


def _graph_activity_result_event_id(activity_id: str) -> str:
    return (
        "harness-graph-activity-result:"
        f"{_graph_required_text(activity_id, 'activity_id')}"
    )


def _graph_observation_event_id(observation_checksum: str) -> str:
    return (
        "harness-graph-observation:"
        f"{_graph_checksum_digest(observation_checksum, 'observation_checksum')}"
    )


def _activated_node_for_projection(commit: HarnessGraphProjectionCommit):
    if commit.commit_kind is not HarnessGraphCommitKind.DECISION_PROJECTION:
        return None
    matches = tuple(
        item
        for item in commit.state.node_instances
        if item.activation_sequence == commit.sequence
        and item.last_event_sequence == commit.sequence
        and item.metadata.get("last_decision_type") == "activate_node"
        and item.metadata.get("last_decision_checksum") == commit.cause_checksum
    )
    if len(matches) > 1:
        raise EventStoreCorruptionError(
            "one graph activation projection created multiple node identities"
        )
    return None if not matches else matches[0]


def _graph_checksum_digest(value: Any, field_name: str) -> str:
    return _graph_checksum(value, field_name).removeprefix("sha256:")


def _graph_checksum(value: Any, field_name: str) -> str:
    if not _valid_checksum_ref(value):
        raise HarnessValidationError(
            f"{field_name} must be a canonical sha256 reference"
        )
    return value


def _graph_required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HarnessValidationError(f"{field_name} must not be blank")
    return value.strip()


def _graph_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EventStoreCorruptionError(f"graph {field_name} must be an object")
    return value


def _graph_array(value: Any, field_name: str) -> tuple[Any, ...]:
    if not isinstance(value, list | tuple):
        raise EventStoreCorruptionError(f"graph {field_name} must be an array")
    return tuple(value)


def _graph_exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    field_name: str,
) -> None:
    if set(value) != expected:
        raise EventStoreCorruptionError(f"{field_name} fields are invalid")


def _validate_graph_commit_checksum(
    value: Mapping[str, Any],
    expected: str,
) -> None:
    if value.get("commit_checksum") != expected:
        raise EventStoreCorruptionError("graph commit checksum is invalid")


def _validate_commit_result(stored: StoredEvent, request: EventPublishRequest) -> None:
    if not isinstance(stored, StoredEvent):
        raise HarnessValidationError(
            "event runtime must return StoredEvent after commit"
        )
    stored.verify_integrity()
    if stored.event_id != request.event_id:
        raise HarnessValidationError(
            "event runtime returned a different Harness event_id"
        )
    if (
        stored.event_type != request.event_type
        or stored.data_schema != request.data_schema
    ):
        raise HarnessValidationError(
            "event runtime returned a different Harness schema identity"
        )
    if stored.stream_id != request.stream_id:
        raise HarnessValidationError(
            "event runtime returned a different Harness stream"
        )


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
        raise HarnessValidationError(
            "stored Harness event has an unexpected producer source"
        )


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
        raise HarnessValidationError(
            "Harness payload run_id conflicts with canonical business context"
        )
    payload_step_id = payload.get("step_id")
    if payload_step_id is not None and (step_id is None or payload_step_id != step_id):
        raise HarnessValidationError(
            "Harness payload step_id conflicts with canonical business context"
        )
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
    if (
        canonical_time is None
        or duplicate_time is None
        or duplicate_time != canonical_time
    ):
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
            payload["gate_results"] = _gate_result_projections(payload["gate_results"])
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
        if isinstance(details, Mapping) and isinstance(
            details.get("harness_gate"), Mapping
        ):
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
        "graph_decision_checksum",
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
        failure = _safe_side_effect_failure_projection(value.get("side_effect_failure"))
        projected["value_ref"] = failure["effect_ref"]
        if "decision_ref" in failure:
            projected["side_effect_decision_ref"] = failure["decision_ref"]
    worker_value = value.get("worker_result", value)
    if any(
        key in value
        for key in (
            "worker_result",
            "status",
            "output",
            "diagnostics",
            "metrics",
            "error",
        )
    ):
        projected["worker_result_ref"] = _value_ref(worker_value)
    projected["decision_payload_ref"] = _value_ref(value)
    return projected


def _safe_side_effect_authorization_projection(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise HarnessValidationError(
            "side-effect authorization projection must be an object"
        )
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
        raise HarnessValidationError(
            "side-effect authorization projection fields are invalid"
        )
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
    if value.get("disposition") not in {
        "candidate",
        "prepared",
        "quarantine",
        "accepted",
    }:
        raise HarnessValidationError("side-effect authorization disposition is invalid")
    return {key: thaw_canonical_json(value[key]) for key in sorted(fields)}


def _safe_side_effect_failure_projection(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise HarnessValidationError("side-effect failure projection must be an object")
    fields = set(value)
    if fields not in (
        {"code", "effect_ref"},
        {"code", "effect_ref", "decision_ref"},
    ):
        raise HarnessValidationError(
            "side-effect failure projection fields are invalid"
        )
    code = value.get("code")
    if not isinstance(code, str) or not code.strip():
        raise HarnessValidationError("side-effect failure code is invalid")
    effect_ref = value.get("effect_ref")
    if not _valid_checksum_ref(effect_ref):
        raise HarnessValidationError(
            "side-effect failure effect_ref must be a sha256 reference"
        )
    projected = {"code": code.strip(), "effect_ref": effect_ref}
    if "decision_ref" in fields:
        decision_ref = value.get("decision_ref")
        if not _valid_checksum_ref(decision_ref):
            raise HarnessValidationError(
                "side-effect failure decision_ref must be a sha256 reference"
            )
        projected["decision_ref"] = decision_ref
    return projected


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
                raise HarnessValidationError(
                    "Harness metadata transition_kind is invalid"
                )
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
        or descriptor.activity_kind is not harness_activity_kind(expected.activity_type)
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


__all__ = [
    "DurableHarnessEventPort",
    "DurableHarnessTransitionPort",
    "HARNESS_DATA_SCHEMA",
    "HARNESS_EVENT_SOURCE",
    "HARNESS_SAFE_PROJECTION",
    "HarnessEventCanonicalAdapter",
]
