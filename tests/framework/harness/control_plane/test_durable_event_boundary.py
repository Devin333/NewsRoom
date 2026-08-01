from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from framework.events.canonical import (
    EventCandidate,
    PayloadReference,
    StoredEvent,
    assert_same_event_identity,
    canonical_json_bytes,
    checksum_for,
    thaw_canonical_json,
)
from framework.events.errors import (
    EventIncompleteHistoryError,
    EventReplayMismatchError,
    EventStoreCorruptionError,
    EventStoreUnavailableError,
    EventStreamVersionConflictError,
)
from framework.events.runtime.activities import (
    REPLAY_ACTIVITY_RECORD_CONTENT_TYPE,
    RecordedActivityPayloadWrite,
    RecordedActivityWrite,
    ReplayActivityRecord,
    ReplayActivityRecordingConflictError,
    ReplayActivityStatus,
)
from framework.events.runtime.models import (
    EventPage,
    StreamReadRequest,
    StreamSequenceCursor,
)
from framework.events.runtime.publisher import EventPublishRequest
from framework.events.schema import (
    REQUIRED_SECURE_PAYLOAD_CAPABILITIES,
    EventSecurityProjector,
    SecurePayloadValidation,
    SecurityClassification,
    default_event_schema_catalog,
)
from framework.harness import (
    DeterministicGate,
    DeterministicGateRegistry,
    GateReference,
    GateRegistration,
    DurableHarnessEventPort,
    DurableHarnessTransitionPort,
    HarnessBudget,
    HarnessControlPlane,
    HarnessEvent,
    HarnessEventCanonicalAdapter,
    HarnessEventType,
    HarnessGraphDecisionType,
    HarnessGraphObservationType,
    HarnessGateResult,
    InMemoryHarnessEventPort,
    HarnessRunSpec,
    HarnessRunStatus,
    HarnessRetryPolicy,
    HarnessState,
    HarnessStepSpec,
    HarnessValidationError,
    HarnessWorkerResult,
    HarnessWorkflowSpec,
    RunLifecycle,
    RunOutcome,
    event_log_entry_from_stored_event,
    transcript_entry_from_stored_event,
)
from framework.harness.control_plane.durable_events import (
    HARNESS_GRAPH_DECISION_EVENT_TYPE,
    HARNESS_GRAPH_OBSERVATION_EVENT_TYPE,
    HARNESS_GRAPH_PROJECTION_EVENT_TYPE,
)
from framework.harness.control_plane.transition import HarnessStateProjection
from framework.shared.json import stable_json_dumps


NOW = datetime(2026, 7, 15, 8, 0, tzinfo=UTC)
FROZEN_V1_RUN_ID = "run-frozen-v1-history"
FROZEN_V1_HISTORY_PATH = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "harness"
    / "durable_events"
    / "v1_transition_history.json"
)


class CanonicalRecordingRuntime:
    def __init__(
        self,
        *,
        fail_before: Callable[[EventPublishRequest], bool] | None = None,
        fail_after: Callable[[EventPublishRequest], bool] | None = None,
    ) -> None:
        self.fail_before = fail_before or (lambda request: False)
        self.fail_after = fail_after or (lambda request: False)
        self.attempts: list[EventPublishRequest] = []
        self.events: list[StoredEvent] = []
        self._by_id: dict[str, StoredEvent] = {}

    def publish(
        self,
        event: EventPublishRequest,
        *,
        expected_last_sequence=None,
        unit_of_work=None,
    ) -> StoredEvent:
        assert unit_of_work is None
        self.attempts.append(event)
        if self.fail_before(event):
            raise EventStoreUnavailableError("durable Harness store is unavailable")
        candidate = EventCandidate(
            event_id=event.event_id,
            event_type=event.event_type,
            data_schema=event.data_schema,
            source=event.source,
            subject=event.subject,
            occurred_at=event.occurred_at,
            stream_id=event.stream_id,
            correlation_id=event.correlation_id,
            causation_id=event.causation_id,
            business_context=event.business_context,
            producer=event.producer,
            trace=event.trace,
            tenant_id=event.tenant_id,
            security_classification=event.security_classification,
            content_type=event.content_type,
            payload=event.payload,
            payload_ref=event.payload_ref,
            extensions=event.extensions,
        )
        existing = self._by_id.get(candidate.event_id)
        if existing is not None:
            assert_same_event_identity(existing, candidate)
            return existing
        actual_last_sequence = (
            self.get_stream_high_watermark(
                event.stream_id,
                tenant_id=event.tenant_id,
            )
            or 0
        )
        if (
            expected_last_sequence is not None
            and expected_last_sequence != actual_last_sequence
        ):
            raise EventStreamVersionConflictError(
                stream_id=event.stream_id,
                expected_last_sequence=expected_last_sequence,
                actual_last_sequence=actual_last_sequence,
            )
        stored = StoredEvent(
            candidate=candidate,
            observed_at=NOW + timedelta(microseconds=len(self.events)),
            stream_sequence=actual_last_sequence + 1,
        )
        self.events.append(stored)
        self._by_id[stored.event_id] = stored
        if self.fail_after(event):
            raise EventStoreUnavailableError("commit outcome was uncertain")
        return stored

    def get_event(self, event_id: str, *, tenant_id=None):
        event = self._by_id.get(event_id)
        if event is None or event.tenant_id != tenant_id:
            return None
        return event

    def get_stream_high_watermark(self, stream_id: str, *, tenant_id=None):
        sequences = [
            event.stream_sequence
            for event in self.events
            if event.stream_id == stream_id and event.tenant_id == tenant_id
        ]
        return max(sequences) if sequences else None

    def read_stream(self, request: StreamReadRequest) -> EventPage:
        high_watermark = self.get_stream_high_watermark(
            request.stream_id,
            tenant_id=request.tenant_id,
        )
        if high_watermark is None:
            return EventPage(
                stream_id=request.stream_id,
                events=(),
                high_watermark=None,
                tenant_id=request.tenant_id,
            )
        high_watermark = min(request.through_sequence or high_watermark, high_watermark)
        after_sequence = (
            request.cursor.after_sequence if request.cursor is not None else 0
        )
        matching = [
            event
            for event in self.events
            if event.stream_id == request.stream_id
            and event.tenant_id == request.tenant_id
            and after_sequence < event.stream_sequence <= high_watermark
            and (not request.event_types or event.event_type in request.event_types)
            and (not request.data_schemas or event.data_schema in request.data_schemas)
        ]
        selected = tuple(matching[: request.limit])
        next_cursor = None
        if len(matching) > request.limit and selected:
            next_cursor = StreamSequenceCursor(
                stream_id=request.stream_id,
                after_sequence=selected[-1].stream_sequence,
                high_watermark=high_watermark,
                tenant_id=request.tenant_id,
            )
        return EventPage(
            stream_id=request.stream_id,
            events=selected,
            high_watermark=high_watermark,
            next_cursor=next_cursor,
            tenant_id=request.tenant_id,
        )

    def replace_payload(self, event: StoredEvent, payload: dict) -> StoredEvent:
        replacement = StoredEvent(
            candidate=replace(event.candidate, payload=payload),
            observed_at=event.observed_at,
            stream_sequence=event.stream_sequence,
        )
        self.events[self.events.index(event)] = replacement
        self._by_id[event.event_id] = replacement
        return replacement

    def seed_stored_events(self, events: tuple[StoredEvent, ...]) -> None:
        if self.events:
            raise ValueError("canonical runtime must be empty before fixture seeding")
        for event in events:
            event.verify_integrity()
            expected_sequence = (
                self.get_stream_high_watermark(
                    event.stream_id,
                    tenant_id=event.tenant_id,
                )
                or 0
            ) + 1
            if event.stream_sequence != expected_sequence:
                raise ValueError("frozen fixture stream sequence is not contiguous")
            if event.event_id in self._by_id:
                raise ValueError("frozen fixture contains a duplicate event identity")
            self.events.append(event)
            self._by_id[event.event_id] = event


class SecureActivityStore:
    def __init__(self) -> None:
        self.payloads: dict[str, RecordedActivityPayloadWrite] = {}
        self.records: dict[str, RecordedActivityWrite] = {}

    def put_payload(self, payload, *, tenant_id, classification):
        self._validate_scope(payload, tenant_id, classification)
        reference = PayloadReference(
            uri=self._uri(tenant_id, payload.activity_id, payload.role.value),
            expected_checksum=payload.content_checksum,
            content_type=payload.content_type,
            size_bytes=len(canonical_json_bytes(payload.content)),
        )
        write = RecordedActivityPayloadWrite(payload, reference)
        existing = self.payloads.get(reference.uri)
        if existing is not None and existing != write:
            raise ReplayActivityRecordingConflictError(
                "activity payload identity collision"
            )
        self.payloads[reference.uri] = write
        return write

    def accept_record(self, record, *, tenant_id, classification):
        self._validate_scope(record.activity, tenant_id, classification)
        existing = self.records.get(record.activity.activity_id)
        if existing is not None:
            if (
                existing.record.activity != record.activity
                or existing.record.outcome.started_at != record.outcome.started_at
            ):
                raise ReplayActivityRecordingConflictError(
                    "activity record identity collision"
                )
            return existing
        write = self._record_write(record)
        self.records[record.activity.activity_id] = write
        return write

    def complete_record(
        self,
        accepted_ref,
        record,
        *,
        tenant_id,
        classification,
    ):
        self._validate_scope(record.activity, tenant_id, classification)
        existing = self.records.get(record.activity.activity_id)
        if existing is None:
            raise ReplayActivityRecordingConflictError("activity was not accepted")
        if existing.record.outcome.status is not ReplayActivityStatus.PENDING:
            if existing.record != record:
                raise ReplayActivityRecordingConflictError(
                    "activity terminal outcome collision"
                )
            return existing
        if (
            existing.recorded_ref != accepted_ref
            or existing.record.activity != record.activity
        ):
            raise ReplayActivityRecordingConflictError(
                "activity completion conflicts with accepted record"
            )
        write = self._record_write(record)
        self.records[record.activity.activity_id] = write
        return write

    def get_record(self, reference, *, tenant_id):
        for write in self.records.values():
            if (
                write.recorded_ref == reference
                and write.record.activity.tenant_id == tenant_id
            ):
                return write.record
        return None

    def get_payload(self, reference, *, tenant_id):
        write = self.payloads.get(reference.uri)
        if (
            write is None
            or write.payload_ref != reference
            or write.payload.tenant_id != tenant_id
        ):
            raise LookupError("recorded activity payload is missing")
        return thaw_canonical_json(write.payload.content)

    def validate_reference(self, reference, *, tenant_id, classification):
        parsed = PayloadReference.from_dict(reference)
        write = next(
            (
                item
                for item in self.records.values()
                if item.recorded_ref == parsed
                and item.record.activity.tenant_id == tenant_id
                and item.record.activity.security_classification is classification
            ),
            None,
        )
        if write is None:
            raise LookupError("secure activity reference is missing")
        return SecurePayloadValidation.for_reference(
            parsed.to_dict(),
            tenant_id=tenant_id,
            classification=classification,
            capabilities=REQUIRED_SECURE_PAYLOAD_CAPABILITIES,
        )

    @staticmethod
    def _validate_scope(value, tenant_id, classification) -> None:
        if (
            value.tenant_id != tenant_id
            or value.security_classification is not classification
        ):
            raise ReplayActivityRecordingConflictError(
                "activity scope conflicts with storage authority"
            )

    @classmethod
    def _record_write(cls, record: ReplayActivityRecord) -> RecordedActivityWrite:
        return RecordedActivityWrite(
            record,
            PayloadReference(
                uri=cls._uri(
                    record.activity.tenant_id,
                    record.activity.activity_id,
                    "record",
                ),
                expected_checksum=record.record_checksum,
                content_type=REPLAY_ACTIVITY_RECORD_CONTENT_TYPE,
                size_bytes=len(canonical_json_bytes(record.to_dict())),
            ),
        )

    @staticmethod
    def _uri(tenant_id, activity_id, role) -> str:
        return f"secure-activity://{tenant_id}/{activity_id}/{role}"


def _durable_port(runtime: CanonicalRecordingRuntime):
    return DurableHarnessTransitionPort(
        runtime,
        runtime,
        secure_activity_store=SecureActivityStore(),
        adapter=HarnessEventCanonicalAdapter(
            tenant_id="tenant-test",
            security_classification=SecurityClassification.INTERNAL,
        ),
    )


def _frozen_v1_history() -> tuple[StoredEvent, ...]:
    fixture = json.loads(FROZEN_V1_HISTORY_PATH.read_text(encoding="utf-8"))
    if set(fixture) != {"events"} or not isinstance(fixture["events"], list):
        raise ValueError("frozen v1 history fixture has an invalid envelope")
    return tuple(StoredEvent.from_dict(event) for event in fixture["events"])


def _frozen_v1_transition(transition_kind: str) -> StoredEvent:
    return next(
        event
        for event in _frozen_v1_history()
        if event.payload is not None
        and event.payload.get("transition_kind") == transition_kind
    )


def _frozen_v1_run_spec() -> HarnessRunSpec:
    return replace(_run_spec(FROZEN_V1_RUN_ID), created_at=NOW)


class CountingGate(DeterministicGate):
    gate_name = "counting"

    def __init__(self) -> None:
        self.calls = 0

    def evaluate(self, context) -> HarnessGateResult:
        self.calls += 1
        return HarnessGateResult(gate_name="counting", passed=True)


class FailOnceGate(DeterministicGate):
    gate_name = "fail_once"

    def __init__(self) -> None:
        self.calls = 0

    def evaluate(self, context) -> HarnessGateResult:
        del context
        self.calls += 1
        return HarnessGateResult(
            gate_name="fail_once",
            passed=self.calls > 1,
        )


class VersionedCountingGate(DeterministicGate):
    gate_name = "candidate_quality"

    def __init__(self) -> None:
        self.calls = 0

    def evaluate(self, context) -> HarnessGateResult:
        self.calls += 1
        return HarnessGateResult(
            gate_name=self.gate_name,
            passed=context.step_state.status.value == "verifying",
            details={"score": 0.9},
        )


def test_control_plane_requires_an_explicit_event_port() -> None:
    with pytest.raises(HarnessValidationError, match="event_port is required"):
        HarnessControlPlane()


def test_typed_harness_event_detaches_and_freezes_nested_transition_content() -> None:
    payload = {"status": "running", "nested": {"attempt": 1}}
    metadata = {"status_before": "created", "labels": ["durable"]}
    event = HarnessEvent(
        event_type=HarnessEventType.RUN_STATE_CHANGED,
        run_id="run-immutable",
        payload=payload,
        metadata=metadata,
        occurred_at=NOW,
    )

    payload["nested"]["attempt"] = 99
    metadata["labels"].append("mutated")

    assert event.payload["nested"]["attempt"] == 1
    assert event.metadata["labels"] == ("durable",)
    with pytest.raises(TypeError):
        event.payload["status"] = "failed"  # type: ignore[index]


def test_typed_harness_event_roundtrips_through_canonical_commit_and_log_projection() -> (
    None
):
    runtime = CanonicalRecordingRuntime()
    port = DurableHarnessEventPort(runtime)
    source = HarnessEvent(
        event_type=HarnessEventType.RUN_STATE_CHANGED,
        run_id="run-durable",
        step_id="collect",
        payload={"status": "running"},
        metadata={
            "status_before": "created",
            "status_after": "running",
            "transition_kind": "run_start",
        },
        occurred_at=NOW,
    )

    projected = port.record(source)

    assert projected.event_id == source.event_id
    assert projected.run_id == source.run_id
    assert projected.step_id == source.step_id
    assert projected.payload == {
        "projection_schema": "harness-safe-summary/v1",
        "status": "running",
    }
    assert len(runtime.events) == 1
    stored = runtime.events[0]
    assert stored.stream_id == "run:run-durable"
    assert stored.stream_sequence == 1
    assert stored.business_context.run_id == "run-durable"
    assert stored.business_context.step_id == "collect"
    entry = port.event_log_entries[0]
    assert entry.event_id == stored.event_id
    assert entry.status_before == "created"
    assert entry.status_after == "running"
    assert entry.stream_sequence == 1
    assert entry.record_checksum == stored.record_checksum


def test_v1_transition_reader_projects_status_and_transcript_phase() -> None:
    stored = _frozen_v1_transition("plan_entry")

    log_entry = event_log_entry_from_stored_event(stored)
    transcript_entry = transcript_entry_from_stored_event(stored)

    assert log_entry.status_after == "planning"
    assert log_entry.metadata["transition_kind"] == "plan_entry"
    assert transcript_entry.entry_id == stored.event_id
    assert transcript_entry.phase == "PLAN"
    assert transcript_entry.metadata["stream_sequence"] == stored.stream_sequence


def test_public_graph_execution_fails_closed_for_v1_only_history() -> None:
    runtime = CanonicalRecordingRuntime()
    runtime.seed_stored_events(_frozen_v1_history())
    port = _durable_port(runtime)
    run_spec = _frozen_v1_run_spec()
    legacy_state = HarnessState.initial(run_spec)
    worker_calls: list[dict] = []

    def worker(task: dict) -> HarnessWorkerResult:
        worker_calls.append(task)
        return HarnessWorkerResult("succeeded", output={"unexpected": True})

    control_plane = HarnessControlPlane(
        event_port=port,
        worker_registry={"collect": worker},
    )

    for action in (
        lambda: control_plane.initialize(run_spec),
        lambda: control_plane.recover_and_run(run_spec),
        lambda: control_plane.resume_after_approval(legacy_state, approved=True),
    ):
        with pytest.raises(EventIncompleteHistoryError, match="Graph initialization"):
            action()

    assert worker_calls == []


def test_read_models_reject_integrity_valid_semantically_invalid_transition() -> None:
    raw = _frozen_v1_transition("run_start").to_dict()
    payload = dict(raw["payload"])
    state_payload = dict(payload["state"])
    state_payload["status"] = "succeeded"
    payload["state"] = state_payload
    payload["after_state_checksum"] = HarnessStateProjection.from_dict(
        {**state_payload, "run_id": FROZEN_V1_RUN_ID}
    ).checksum
    raw["payload"] = payload
    invalid = StoredEvent.from_dict(raw, verify_checksum=False)

    with pytest.raises(EventStoreCorruptionError, match="control-plane semantics"):
        event_log_entry_from_stored_event(invalid)
    with pytest.raises(EventStoreCorruptionError, match="control-plane semantics"):
        transcript_entry_from_stored_event(invalid)


def test_read_models_reject_wrong_harness_source_before_projection() -> None:
    runtime = CanonicalRecordingRuntime()
    port = _durable_port(runtime)
    port.record(
        HarnessEvent(
            event_type=HarnessEventType.RUN_CREATED,
            run_id="run-invalid-source",
            occurred_at=NOW,
        )
    )
    raw = runtime.events[-1].to_dict()
    raw["source"] = "io.example.untrusted"
    invalid = StoredEvent.from_dict(raw, verify_checksum=False)

    with pytest.raises(EventStoreCorruptionError, match="source"):
        event_log_entry_from_stored_event(invalid)
    with pytest.raises(EventStoreCorruptionError, match="source"):
        transcript_entry_from_stored_event(invalid)


def test_read_models_reject_transition_with_conflicting_expected_stream_head() -> None:
    raw = _frozen_v1_transition("initialize").to_dict()
    payload = dict(raw["payload"])
    payload["expected_last_sequence"] = raw["stream_sequence"]
    raw["payload"] = payload
    invalid = StoredEvent.from_dict(raw, verify_checksum=False)

    with pytest.raises(EventStoreCorruptionError, match="expected stream head"):
        event_log_entry_from_stored_event(invalid)
    with pytest.raises(EventStoreCorruptionError, match="expected stream head"):
        transcript_entry_from_stored_event(invalid)


def test_secure_activity_event_projects_only_integrity_bound_refs() -> None:
    secret = "sk-secure-activity-read-model"
    runtime = CanonicalRecordingRuntime()
    port = _durable_port(runtime)
    result = HarnessControlPlane(
        event_port=port,
        worker_registry={
            "collect": lambda task: HarnessWorkerResult(
                status="succeeded",
                output={"answer": secret},
            )
        },
    ).run(_run_spec("run-activity-read-model"))
    stored = next(event for event in runtime.events if event.payload_ref is not None)
    live_projection = next(
        event for event in result.events if event.event_id == stored.event_id
    )
    recovered_projection = next(
        event
        for event in port.read_history("run-activity-read-model")
        if event.event_id == stored.event_id
    )

    log_entry = event_log_entry_from_stored_event(stored)
    transcript_entry = transcript_entry_from_stored_event(stored)

    assert log_entry.worker_type == "llm"
    assert log_entry.input_ref.startswith("sha256:")
    assert log_entry.output_ref == stored.payload_ref.expected_checksum
    assert log_entry.metadata["activity_status"] == "succeeded"
    assert transcript_entry.entry_id == stored.event_id
    assert transcript_entry.phase == "EXECUTE"
    assert transcript_entry.metadata["event_payload"]["output_ref"] == (
        stored.payload_ref.expected_checksum
    )
    assert live_projection.to_dict() == recovered_projection.to_dict()
    assert secret not in stable_json_dumps(log_entry.to_dict())
    assert secret not in stable_json_dumps(transcript_entry.to_dict())


def test_worker_activity_projection_persists_refs_without_raw_secret_content() -> None:
    runtime = CanonicalRecordingRuntime()
    port = DurableHarnessEventPort(runtime)
    secret = "sk-harness-raw-secret"
    event = HarnessEvent(
        event_type=HarnessEventType.WORKER_RESULT_RECORDED,
        run_id="run-redacted-worker",
        step_id="collect",
        payload={
            "status": "failed",
            "output": {"api_key": secret},
            "artifacts": [],
            "diagnostics": {"authorization": secret},
            "metrics": {"attempts": 1},
            "error": f"worker rejected {secret}",
        },
        metadata={
            "credential_ref": secret,
            "operator_note": f"do not persist {secret}",
            "safe_refs": [secret],
        },
        occurred_at=NOW,
    )

    port.record(event)

    serialized = stable_json_dumps(runtime.events[0].to_dict())
    assert secret not in serialized
    assert runtime.events[0].payload["output_ref"].startswith("sha256:")
    assert runtime.events[0].payload["diagnostics_ref"].startswith("sha256:")
    assert runtime.events[0].payload["error_ref"].startswith("sha256:")
    assert (
        runtime.events[0].extensions["harness"]["metadata"]["omitted_metadata_count"]
        == 3
    )
    assert (
        runtime.events[0]
        .extensions["harness"]["metadata"]["omitted_metadata_ref"]
        .startswith("sha256:")
    )


def test_default_catalog_accepts_adapter_summaries_without_raw_worker_or_gate_content() -> (
    None
):
    secret = "harness-secret-that-must-not-persist"
    adapter = HarnessEventCanonicalAdapter()
    catalog = default_event_schema_catalog()
    projector = EventSecurityProjector()
    events = (
        HarnessEvent(
            event_type=HarnessEventType.PHASE_RECORDED,
            run_id="run-catalog",
            step_id="collect",
            payload={
                "phase": "verify",
                "boundary": "exit",
                "step_id": "collect",
                "input_refs": [],
                "output_refs": [],
                "gate_results": [
                    {
                        "gate": "quality",
                        "passed": False,
                        "details": {"answer": secret},
                    }
                ],
                "metadata": {"turn_count": 2},
                "occurred_at": "2026-07-15T08:00:00Z",
            },
            occurred_at=NOW,
        ),
        HarnessEvent(
            event_type=HarnessEventType.DECISION_RECORDED,
            run_id="run-catalog",
            step_id="collect",
            payload={
                "decision_type": "retry_step",
                "run_id": "run-catalog",
                "step_id": "collect",
                "target_step_id": None,
                "reason": secret,
                "payload": {"worker_result": {"output": secret}},
                "decided_by": "harness",
                "decided_at": "2026-07-15T08:00:00Z",
            },
            occurred_at=NOW,
        ),
        HarnessEvent(
            event_type=HarnessEventType.WORKER_CALLED,
            run_id="run-catalog",
            step_id="collect",
            payload={
                "run_id": "run-catalog",
                "step_id": "collect",
                "worker_type": "llm",
                "activity_id": "harness-activity:" + "1" * 64,
                "idempotency_key": "harness-activity:" + "1" * 64,
                "activity_attempt": 1,
                "activity_contract_version": ("newsroom.harness-worker-activity/v1"),
                "inputs": {"prompt": secret},
                "metadata": {"model_hint": secret},
            },
            occurred_at=NOW,
        ),
        HarnessEvent(
            event_type=HarnessEventType.WORKER_RESULT_RECORDED,
            run_id="run-catalog",
            step_id="collect",
            payload={
                "status": "failed",
                "output": {"answer": secret},
                "artifacts": [],
                "diagnostics": {"provider": secret},
                "metrics": {"latency_ms": 1},
                "error": secret,
            },
            occurred_at=NOW,
        ),
        HarnessEvent(
            event_type=HarnessEventType.GATE_EVALUATED,
            run_id="run-catalog",
            step_id="collect",
            payload={
                "gate": "quality",
                "passed": False,
                "reason": secret,
                "details": {"answer": secret},
            },
            occurred_at=NOW,
        ),
    )

    serialized = []
    for event in events:
        request = adapter.to_publish_request(event)
        registration = catalog.get(request.event_type, request.data_schema)
        validated = catalog.validate(
            request.event_type,
            request.data_schema,
            request.payload or {},
        )
        projection = projector.project(
            payload=validated,
            payload_ref=request.payload_ref,
            extensions=request.extensions,
            policy=registration.sensitivity_policy,
            classification=request.security_classification,
            tenant_id=request.tenant_id,
        )
        serialized.append(stable_json_dumps(projection.payload))
        serialized.append(stable_json_dumps(projection.extensions))

    assert secret not in "".join(serialized)


def test_adapter_rejects_non_boolean_gate_result_without_type_coercion() -> None:
    with pytest.raises(HarnessValidationError, match="passed must be a boolean"):
        HarnessEventCanonicalAdapter().to_publish_request(
            HarnessEvent(
                event_type=HarnessEventType.PHASE_RECORDED,
                run_id="run-invalid-gate",
                step_id="collect",
                payload={
                    "phase": "verify",
                    "boundary": "exit",
                    "step_id": "collect",
                    "input_refs": [],
                    "output_refs": [],
                    "gate_results": [{"gate": "quality", "passed": "false"}],
                    "metadata": {},
                    "occurred_at": "2026-07-15T08:00:00Z",
                },
                occurred_at=NOW,
            )
        )


def test_commit_then_process_crash_keeps_store_authoritative_and_retry_is_idempotent() -> (
    None
):
    fail_once = True

    def fail_after(request: EventPublishRequest) -> bool:
        nonlocal fail_once
        if fail_once:
            fail_once = False
            return True
        return False

    runtime = CanonicalRecordingRuntime(fail_after=fail_after)
    first_port = DurableHarnessEventPort(runtime)
    event = HarnessEvent(
        event_type=HarnessEventType.RUN_CREATED, run_id="run-crash", occurred_at=NOW
    )

    with pytest.raises(EventStoreUnavailableError, match="uncertain"):
        first_port.record(event)

    assert len(runtime.events) == 1
    assert first_port.events == []
    recovered_entry = event_log_entry_from_stored_event(runtime.events[0])
    assert recovered_entry.run_id == "run-crash"
    assert recovered_entry.stream_sequence == 1

    recovered_port = DurableHarnessEventPort(runtime)
    projected = recovered_port.record(event)
    assert projected.event_id == runtime.events[0].event_id
    assert len(runtime.events) == 1
    assert recovered_port.event_log_entries[0].stream_sequence == 1


def test_phase_entry_commit_failure_prevents_gate_and_projection_progress() -> None:
    gate = CountingGate()
    runtime = CanonicalRecordingRuntime(
        fail_before=lambda request: (
            request.event_type == HarnessEventType.PHASE_RECORDED
            and request.payload is not None
            and request.payload.get("phase") == "plan"
            and request.payload.get("boundary") == "entry"
        )
    )
    port = _durable_port(runtime)
    control_plane = HarnessControlPlane(
        event_port=port,
        plan_gates=(gate,),
        worker_registry={
            "collect": lambda task: HarnessWorkerResult(status="succeeded")
        },
    )

    with pytest.raises(EventStoreUnavailableError):
        control_plane.run(_run_spec("run-plan-failure"))

    assert gate.calls == 0
    assert all(
        not (
            event.event_type == HarnessEventType.PHASE_RECORDED
            and event.payload.get("boundary") == "entry"
            and event.payload.get("phase") == "plan"
        )
        for event in port.events
    )


def test_worker_is_not_called_until_worker_activity_event_commits() -> None:
    worker_calls = 0

    def worker(task) -> HarnessWorkerResult:
        nonlocal worker_calls
        worker_calls += 1
        return HarnessWorkerResult(status="succeeded")

    runtime = CanonicalRecordingRuntime(
        fail_before=lambda request: request.event_type == HarnessEventType.WORKER_CALLED
    )
    port = _durable_port(runtime)

    run_spec = _run_spec("run-worker-failure")
    control_plane = HarnessControlPlane(
        event_port=port, worker_registry={"collect": worker}
    )
    with pytest.raises(EventStoreUnavailableError):
        control_plane.run(run_spec)

    assert worker_calls == 0
    assert all(
        event.event_type != HarnessEventType.WORKER_CALLED for event in port.events
    )


def test_verify_recovery_requires_and_reuses_exact_declared_gate_version() -> None:
    fail_once = True
    worker_calls = 0
    gate = VersionedCountingGate()

    def fail_after(request: EventPublishRequest) -> bool:
        nonlocal fail_once
        if fail_once and _is_graph_decision_request(
            request,
            HarnessGraphDecisionType.COMPLETE_NODE,
        ):
            fail_once = False
            return True
        return False

    def worker(task) -> HarnessWorkerResult:
        nonlocal worker_calls
        worker_calls += 1
        return HarnessWorkerResult(status="succeeded", output={"candidate": True})

    runtime = CanonicalRecordingRuntime(fail_after=fail_after)
    secure_store = SecureActivityStore()

    def build_port() -> DurableHarnessTransitionPort:
        return DurableHarnessTransitionPort(
            runtime,
            runtime,
            secure_activity_store=secure_store,
            adapter=HarnessEventCanonicalAdapter(tenant_id="tenant-test"),
        )

    run_spec = HarnessRunSpec(
        run_id="run-versioned-verify-recovery",
        workflow=HarnessWorkflowSpec(
            workflow_id="versioned-verify-recovery",
            steps=(
                HarnessStepSpec(
                    step_id="collect",
                    worker_type="llm",
                    quality_gate="candidate_quality@1",
                ),
            ),
            entry_step_id="collect",
        ),
    )
    registration = GateRegistration(
        reference=GateReference.parse("candidate_quality@1"),
        gate=gate,
    )

    with pytest.raises(EventStoreUnavailableError, match="uncertain"):
        HarnessControlPlane(
            event_port=build_port(),
            worker_registry={"collect": worker},
            gate_registry=DeterministicGateRegistry((registration,)),
        ).run(run_spec)

    with pytest.raises(HarnessValidationError) as missing:
        HarnessControlPlane(
            event_port=build_port(),
            worker_registry={"collect": worker},
            gate_registry=DeterministicGateRegistry(),
        ).recover_and_run(run_spec)
    assert missing.value.code == "unknown_gate_reference"

    recovered = HarnessControlPlane(
        event_port=build_port(),
        worker_registry={"collect": worker},
        gate_registry=DeterministicGateRegistry((registration,)),
    ).recover_and_run(run_spec)

    assert recovered.succeeded is True
    assert worker_calls == 1
    assert gate.calls == 1
    assert recovered.quality_verdicts["collect"].score == 0.9


def test_recovery_reuses_terminal_activity_when_result_event_commit_failed() -> None:
    fail_result_commit_once = True
    worker_tasks: list[dict] = []

    def fail_before(request: EventPublishRequest) -> bool:
        nonlocal fail_result_commit_once
        if (
            fail_result_commit_once
            and request.event_type == HarnessEventType.WORKER_RESULT_RECORDED
        ):
            fail_result_commit_once = False
            return True
        return False

    def worker(task) -> HarnessWorkerResult:
        worker_tasks.append(task)
        return HarnessWorkerResult(status="succeeded", output={"answer": "ready"})

    runtime = CanonicalRecordingRuntime(fail_before=fail_before)
    secure_store = SecureActivityStore()

    def build_port() -> DurableHarnessTransitionPort:
        return DurableHarnessTransitionPort(
            runtime,
            runtime,
            secure_activity_store=secure_store,
            adapter=HarnessEventCanonicalAdapter(tenant_id="tenant-test"),
        )

    run_spec = _run_spec("run-orphan-execute-entry")
    with pytest.raises(EventStoreUnavailableError):
        HarnessControlPlane(
            event_port=build_port(),
            worker_registry={"collect": worker},
        ).run(run_spec)

    dispatch_projection = next(
        event
        for event in runtime.events
        if event.event_type == HARNESS_GRAPH_PROJECTION_EVENT_TYPE
        and _graph_commit(event).get("activity") is not None
    )
    activity = _graph_commit(dispatch_projection)["activity"]
    dispatch_decision = next(
        event
        for event in runtime.events
        if _is_graph_decision_event(
            event,
            HarnessGraphDecisionType.DISPATCH_ACTIVITY,
        )
    )
    recovered = HarnessControlPlane(
        event_port=build_port(),
        worker_registry={"collect": worker},
    ).recover_and_run(run_spec)

    assert recovered.succeeded is True
    assert len(worker_tasks) == 1
    assert worker_tasks[0]["harness_activity"] == {
        "activity_id": activity["activity_id"],
        "idempotency_key": activity["idempotency_key"],
        "attempt": 1,
        "contract_version": "newsroom.harness-worker-activity/v1",
    }
    assert dispatch_decision.stream_sequence < dispatch_projection.stream_sequence
    assert (
        activity["causal_decision_checksum"]
        == _graph_decision(dispatch_decision)["decision_checksum"]
    )
    assert (
        sum(
            _is_graph_decision_event(
                event,
                HarnessGraphDecisionType.DISPATCH_ACTIVITY,
            )
            for event in runtime.events
        )
        == 1
    )
    assert (
        sum(
            event.event_type == HarnessEventType.WORKER_RESULT_RECORDED
            for event in runtime.events
        )
        == 1
    )


def test_recovery_executes_activity_when_worker_call_marker_never_committed() -> None:
    fail_marker_once = True
    worker_tasks: list[dict] = []

    def fail_before(request: EventPublishRequest) -> bool:
        nonlocal fail_marker_once
        if fail_marker_once and request.event_type == HarnessEventType.WORKER_CALLED:
            fail_marker_once = False
            return True
        return False

    def worker(task) -> HarnessWorkerResult:
        worker_tasks.append(task)
        return HarnessWorkerResult(status="succeeded", output={"answer": "ready"})

    runtime = CanonicalRecordingRuntime(fail_before=fail_before)
    secure_store = SecureActivityStore()

    def build_port() -> DurableHarnessTransitionPort:
        return DurableHarnessTransitionPort(
            runtime,
            runtime,
            secure_activity_store=secure_store,
            adapter=HarnessEventCanonicalAdapter(tenant_id="tenant-test"),
        )

    run_spec = _run_spec("run-missing-worker-marker")
    with pytest.raises(EventStoreUnavailableError):
        HarnessControlPlane(
            event_port=build_port(),
            worker_registry={"collect": worker},
        ).run(run_spec)

    assert worker_tasks == []
    recovered = HarnessControlPlane(
        event_port=build_port(),
        worker_registry={"collect": worker},
    ).recover_and_run(run_spec)

    assert recovered.succeeded is True
    assert len(worker_tasks) == 1
    assert worker_tasks[0]["harness_activity"]["attempt"] == 1


def test_recovery_fails_closed_when_worker_call_marker_commit_is_uncertain() -> None:
    worker_calls = 0

    def worker(task) -> HarnessWorkerResult:
        nonlocal worker_calls
        worker_calls += 1
        return HarnessWorkerResult(status="succeeded", output={"answer": "ready"})

    runtime = CanonicalRecordingRuntime(
        fail_after=lambda request: request.event_type == HarnessEventType.WORKER_CALLED
    )
    secure_store = SecureActivityStore()

    def build_port() -> DurableHarnessTransitionPort:
        return DurableHarnessTransitionPort(
            runtime,
            runtime,
            secure_activity_store=secure_store,
            adapter=HarnessEventCanonicalAdapter(tenant_id="tenant-test"),
        )

    run_spec = _run_spec("run-uncertain-worker-marker")
    with pytest.raises(EventStoreUnavailableError, match="uncertain"):
        HarnessControlPlane(
            event_port=build_port(),
            worker_registry={"collect": worker},
        ).run(run_spec)

    with pytest.raises(EventIncompleteHistoryError, match="re-execution is forbidden"):
        HarnessControlPlane(
            event_port=build_port(),
            worker_registry={"collect": worker},
        ).recover_and_run(run_spec)

    assert worker_calls == 0
    assert (
        sum(
            event.event_type == HarnessEventType.WORKER_CALLED
            for event in runtime.events
        )
        == 1
    )


@pytest.mark.parametrize(
    ("field_name", "conflicting_value"),
    [
        ("projection_schema", None),
        ("worker_type", "skill"),
        ("activity_id", None),
        ("idempotency_key", "harness-activity:conflict"),
        ("activity_attempt", 2),
        (
            "activity_contract_version",
            "newsroom.harness-worker-activity/v2",
        ),
    ],
)
def test_recovery_rejects_corrupt_worker_call_marker_descriptor(
    field_name: str,
    conflicting_value,
) -> None:
    worker_calls = 0

    def worker(task) -> HarnessWorkerResult:
        nonlocal worker_calls
        worker_calls += 1
        return HarnessWorkerResult(status="succeeded", output={"answer": "ready"})

    runtime = CanonicalRecordingRuntime(
        fail_after=lambda request: request.event_type == HarnessEventType.WORKER_CALLED
    )
    secure_store = SecureActivityStore()

    def build_port() -> DurableHarnessTransitionPort:
        return DurableHarnessTransitionPort(
            runtime,
            runtime,
            secure_activity_store=secure_store,
            adapter=HarnessEventCanonicalAdapter(tenant_id="tenant-test"),
        )

    run_spec = _run_spec(f"run-corrupt-worker-marker-{field_name}")
    with pytest.raises(EventStoreUnavailableError):
        HarnessControlPlane(
            event_port=build_port(),
            worker_registry={"collect": worker},
        ).run(run_spec)

    marker = next(
        event
        for event in runtime.events
        if event.event_type == HarnessEventType.WORKER_CALLED
    )
    payload = dict(marker.payload or {})
    if conflicting_value is None:
        payload.pop(field_name)
    else:
        payload[field_name] = conflicting_value
    runtime.replace_payload(marker, payload)

    with pytest.raises(EventStoreCorruptionError, match="worker call marker"):
        HarnessControlPlane(
            event_port=build_port(),
            worker_registry={"collect": worker},
        ).recover_and_run(run_spec)

    assert worker_calls == 0


def test_in_memory_recovery_does_not_bind_a_previous_attempt_result() -> None:
    class FailSecondWorkerMarkerPort(InMemoryHarnessEventPort):
        def __init__(self) -> None:
            super().__init__()
            self.worker_markers = 0

        def record(self, event):
            if event.event_type == HarnessEventType.WORKER_CALLED:
                self.worker_markers += 1
                if self.worker_markers == 2:
                    raise EventStoreUnavailableError(
                        "second worker marker did not commit"
                    )
            return super().record(event)

    worker_calls = 0

    def worker(task) -> HarnessWorkerResult:
        nonlocal worker_calls
        worker_calls += 1
        if worker_calls == 1:
            return HarnessWorkerResult(status="failed", error="retry")
        return HarnessWorkerResult(status="succeeded", output={"answer": "fresh"})

    port = FailSecondWorkerMarkerPort()
    workflow = HarnessWorkflowSpec(
        workflow_id="in-memory-attempt-recovery",
        steps=(
            HarnessStepSpec(
                step_id="collect",
                worker_type="llm",
                retry_policy=HarnessRetryPolicy(
                    max_attempts=2,
                    retry_on_statuses=("failed",),
                ),
            ),
        ),
        entry_step_id="collect",
    )
    run_spec = HarnessRunSpec(
        run_id="run-in-memory-attempt-recovery",
        workflow=workflow,
    )
    with pytest.raises(EventStoreUnavailableError):
        HarnessControlPlane(
            event_port=port,
            worker_registry={"collect": worker},
        ).run(run_spec)

    recovered = HarnessControlPlane(
        event_port=port,
        worker_registry={"collect": worker},
    ).recover_and_run(run_spec)

    assert recovered.succeeded is True
    assert worker_calls == 2
    assert recovered.worker_results["collect"].output == {"answer": "fresh"}


def test_retry_recovery_clears_previous_activity_result_and_error_metadata() -> None:
    worker_call_events = 0
    worker_calls = 0
    worker_tasks: list[dict] = []

    def fail_before(request: EventPublishRequest) -> bool:
        nonlocal worker_call_events
        if request.event_type != HarnessEventType.WORKER_CALLED:
            return False
        worker_call_events += 1
        return worker_call_events == 2

    def worker(task) -> HarnessWorkerResult:
        nonlocal worker_calls
        worker_calls += 1
        worker_tasks.append(task)
        if worker_calls == 1:
            return HarnessWorkerResult(status="failed", error="attempt one failed")
        return HarnessWorkerResult(status="succeeded", output={"answer": "recovered"})

    runtime = CanonicalRecordingRuntime(fail_before=fail_before)
    secure_store = SecureActivityStore()

    def build_port() -> DurableHarnessTransitionPort:
        return DurableHarnessTransitionPort(
            runtime,
            runtime,
            secure_activity_store=secure_store,
            adapter=HarnessEventCanonicalAdapter(tenant_id="tenant-test"),
        )

    workflow = HarnessWorkflowSpec(
        workflow_id="retry-recovery",
        steps=(
            HarnessStepSpec(
                step_id="collect",
                worker_type="llm",
                retry_policy=HarnessRetryPolicy(
                    max_attempts=2,
                    retry_on_statuses=("failed",),
                ),
            ),
        ),
        entry_step_id="collect",
    )
    run_spec = HarnessRunSpec(run_id="run-retry-recovery", workflow=workflow)
    with pytest.raises(EventStoreUnavailableError):
        HarnessControlPlane(
            event_port=build_port(),
            worker_registry={"collect": worker},
        ).run(run_spec)

    recovered = HarnessControlPlane(
        event_port=build_port(),
        worker_registry={"collect": worker},
    ).recover_and_run(run_spec)
    dispatch_projections = [
        event
        for event in runtime.events
        if event.event_type == HARNESS_GRAPH_PROJECTION_EVENT_TYPE
        and _graph_commit(event).get("activity") is not None
    ]
    activities = [_graph_commit(event)["activity"] for event in dispatch_projections]
    second_state = _graph_commit(dispatch_projections[-1])["state"]
    second_node = second_state["node_instances"][0]

    assert recovered.succeeded is True
    assert worker_calls == 2
    assert [task["harness_activity"]["attempt"] for task in worker_tasks] == [1, 2]
    assert len(dispatch_projections) == 2
    assert [activity["attempt"] for activity in activities] == [1, 2]
    assert activities[0]["activity_id"] != activities[1]["activity_id"]
    assert activities[0]["idempotency_key"] == activities[1]["idempotency_key"]
    assert [activity["fencing_generation"] for activity in activities] == [1, 2]
    assert second_node["attempt"] == 2
    assert second_node["step_status"] == "running"
    assert second_node["error_code"] is None
    assert [item["activity_id"] for item in second_state["active_activities"]] == [
        activities[1]["activity_id"]
    ]


def test_multistep_recovery_hydrates_prior_outputs_for_downstream_worker() -> None:
    fail_second_plan_once = True
    first_worker_calls = 0
    second_worker_tasks: list[dict] = []

    def fail_before(request: EventPublishRequest) -> bool:
        nonlocal fail_second_plan_once
        if fail_second_plan_once and _is_graph_decision_request(
            request,
            HarnessGraphDecisionType.ENTER_STEP_PHASE,
            node_id="consume",
            reason_code="plan_requested",
        ):
            fail_second_plan_once = False
            return True
        return False

    def collect_worker(task) -> HarnessWorkerResult:
        nonlocal first_worker_calls
        first_worker_calls += 1
        return HarnessWorkerResult(
            status="succeeded",
            output={"answer": "durable-prior-output"},
        )

    def consume_worker(task) -> HarnessWorkerResult:
        second_worker_tasks.append(task)
        return HarnessWorkerResult(status="succeeded", output={"done": True})

    runtime = CanonicalRecordingRuntime(fail_before=fail_before)
    secure_store = SecureActivityStore()

    def build_port() -> DurableHarnessTransitionPort:
        return DurableHarnessTransitionPort(
            runtime,
            runtime,
            secure_activity_store=secure_store,
            adapter=HarnessEventCanonicalAdapter(tenant_id="tenant-test"),
        )

    workflow = HarnessWorkflowSpec(
        workflow_id="multistep-recovery",
        steps=(
            HarnessStepSpec(
                step_id="collect",
                worker_type="llm",
                output_key="collected",
            ),
            HarnessStepSpec(
                step_id="consume",
                worker_type="llm",
                input_keys=("collected",),
            ),
        ),
        entry_step_id="collect",
    )
    run_spec = HarnessRunSpec(run_id="run-multistep-recovery", workflow=workflow)
    worker_registry = {
        "collect": collect_worker,
        "consume": consume_worker,
    }
    with pytest.raises(EventStoreUnavailableError):
        HarnessControlPlane(
            event_port=build_port(),
            worker_registry=worker_registry,
        ).run(run_spec)

    recovered = HarnessControlPlane(
        event_port=build_port(),
        worker_registry=worker_registry,
    ).recover_and_run(run_spec)

    assert recovered.succeeded is True
    assert first_worker_calls == 1
    assert len(second_worker_tasks) == 1
    assert second_worker_tasks[0]["inputs"]["collected"] == {
        "answer": "durable-prior-output"
    }
    assert recovered.state.metadata["outputs"]["collected"] == {
        "answer": "durable-prior-output"
    }


def test_same_run_id_isolated_by_tenant_has_disjoint_canonical_identities() -> None:
    runtime = CanonicalRecordingRuntime()
    secure_store = SecureActivityStore()
    run_spec = _run_spec("shared-tenant-run")

    def build_port(tenant_id: str) -> DurableHarnessTransitionPort:
        return DurableHarnessTransitionPort(
            runtime,
            runtime,
            secure_activity_store=secure_store,
            adapter=HarnessEventCanonicalAdapter(tenant_id=tenant_id),
        )

    tenant_a = HarnessControlPlane(
        event_port=build_port("tenant-a"),
        worker_registry={
            "collect": lambda task: HarnessWorkerResult(
                status="succeeded",
                output={"tenant": "a"},
            )
        },
    ).run(run_spec)
    tenant_b = HarnessControlPlane(
        event_port=build_port("tenant-b"),
        worker_registry={
            "collect": lambda task: HarnessWorkerResult(
                status="succeeded",
                output={"tenant": "b"},
            )
        },
    ).run(run_spec)
    tenant_a_events = [
        event for event in runtime.events if event.tenant_id == "tenant-a"
    ]
    tenant_b_events = [
        event for event in runtime.events if event.tenant_id == "tenant-b"
    ]

    assert tenant_a.succeeded is True
    assert tenant_b.succeeded is True
    assert {event.event_id for event in tenant_a_events}.isdisjoint(
        event.event_id for event in tenant_b_events
    )
    assert [event.stream_sequence for event in tenant_a_events] == list(
        range(1, len(tenant_a_events) + 1)
    )
    assert [event.stream_sequence for event in tenant_b_events] == list(
        range(1, len(tenant_b_events) + 1)
    )
    assert all(
        event.event_id.startswith(("harness-event-v2:", "harness-transition-v2:"))
        for event in (*tenant_a_events, *tenant_b_events)
    )


def test_terminal_commit_failure_never_returns_memory_only_success() -> None:
    runtime = CanonicalRecordingRuntime(
        fail_before=lambda request: _is_graph_decision_request(
            request,
            HarnessGraphDecisionType.COMPLETE_RUN,
        )
    )
    port = _durable_port(runtime)
    run_spec = _run_spec("run-terminal-failure")

    with pytest.raises(EventStoreUnavailableError):
        HarnessControlPlane(
            event_port=port,
            worker_registry={
                "collect": lambda task: HarnessWorkerResult(status="succeeded")
            },
        ).run(run_spec)

    recovery = port.recover_graph(run_spec.run_id)
    assert recovery.state.lifecycle is RunLifecycle.RUNNING
    assert recovery.state.outcome is RunOutcome.NONE
    assert recovery.state.node_instances[0].status.value == "succeeded"
    assert not any(
        _is_graph_decision_event(event, HarnessGraphDecisionType.COMPLETE_RUN)
        for event in runtime.events
    )
    assert all(
        _graph_projection_state(event).get("lifecycle") != RunLifecycle.COMPLETED.value
        for event in runtime.events
        if event.event_type == HARNESS_GRAPH_PROJECTION_EVENT_TYPE
    )


def test_plan_execute_verify_entry_and_exit_are_committed_in_order() -> None:
    runtime = CanonicalRecordingRuntime()
    port = _durable_port(runtime)
    result = HarnessControlPlane(
        event_port=port,
        worker_registry={
            "collect": lambda task: HarnessWorkerResult(status="succeeded")
        },
    ).run(_run_spec("run-phase-order"))

    assert result.state.status == HarnessRunStatus.SUCCEEDED
    boundaries = [
        (event.payload["phase"], event.payload["boundary"])
        for event in result.events
        if event.event_type == HarnessEventType.PHASE_RECORDED
    ]
    assert boundaries == [
        ("plan", "entry"),
        ("plan", "exit"),
        ("execute", "entry"),
        ("execute", "exit"),
        ("verify", "entry"),
        ("verify", "exit"),
    ]
    assert [event.stream_sequence for event in runtime.events] == list(
        range(1, len(runtime.events) + 1)
    )
    decision_events = [
        event
        for event in runtime.events
        if event.event_type == HARNESS_GRAPH_DECISION_EVENT_TYPE
    ]
    assert [_graph_decision(event)["decision_type"] for event in decision_events] == [
        HarnessGraphDecisionType.ACTIVATE_NODE.value,
        HarnessGraphDecisionType.ENTER_STEP_PHASE.value,
        HarnessGraphDecisionType.DISPATCH_ACTIVITY.value,
        HarnessGraphDecisionType.VERIFY_ACTIVITY_RESULT.value,
        HarnessGraphDecisionType.COMPLETE_NODE.value,
        HarnessGraphDecisionType.COMPLETE_RUN.value,
    ]
    for decision_event in decision_events:
        projection = _causal_graph_projection(runtime.events, decision_event)
        assert decision_event.stream_sequence < projection.stream_sequence

    recovery = port.recover_graph("run-phase-order")
    assert recovery.state.lifecycle is RunLifecycle.COMPLETED
    assert recovery.state.outcome is RunOutcome.SUCCEEDED
    assert recovery.pending_decisions == ()


def test_approval_resume_commits_before_continuation_and_does_not_repeat_worker() -> (
    None
):
    worker_calls = 0

    def worker(task) -> HarnessWorkerResult:
        nonlocal worker_calls
        worker_calls += 1
        return HarnessWorkerResult(status="succeeded", output={"candidate": "ready"})

    runtime = CanonicalRecordingRuntime()
    port = _durable_port(runtime)
    control_plane = HarnessControlPlane(
        event_port=port, worker_registry={"collect": worker}
    )
    waiting = control_plane.run(_run_spec("run-approval", approval_required=True))
    assert waiting.state.status == HarnessRunStatus.WAITING_APPROVAL
    before_resume = len(runtime.events)

    resumed = control_plane.resume_after_approval(waiting.state, approved=True)

    assert resumed.state.status == HarnessRunStatus.SUCCEEDED
    assert worker_calls == 1
    resumed_events = runtime.events[before_resume:]
    approval_event = resumed_events[0]
    assert approval_event.event_type == HARNESS_GRAPH_OBSERVATION_EVENT_TYPE
    approval = _graph_observation(approval_event)
    assert approval["observation_type"] == HarnessGraphObservationType.WAIT_CAUSE.value
    assert approval["attempt"] == 1
    assert approval["payload"]["cause_kind"] == "approval"
    assert approval["payload"]["record"]["approved"] is True
    approval_projection = _causal_graph_projection(
        runtime.events,
        approval_event,
    )
    verify_decision = next(
        event
        for event in resumed_events
        if _is_graph_decision_event(
            event,
            HarnessGraphDecisionType.VERIFY_ACTIVITY_RESULT,
            reason_code="approval_granted_verify",
        )
    )
    verify_projection = _causal_graph_projection(runtime.events, verify_decision)
    assert (
        approval_event.stream_sequence
        < approval_projection.stream_sequence
        < verify_decision.stream_sequence
        < verify_projection.stream_sequence
    )
    recovery = port.recover_graph("run-approval")
    assert recovery.state.lifecycle is RunLifecycle.COMPLETED
    assert recovery.state.outcome is RunOutcome.SUCCEEDED


def test_replan_requires_fresh_approval_for_the_new_activity_attempt() -> None:
    worker_calls = 0
    gate = FailOnceGate()

    def worker(task) -> HarnessWorkerResult:
        nonlocal worker_calls
        worker_calls += 1
        return HarnessWorkerResult(
            status="succeeded",
            output={"candidate": f"attempt-{worker_calls}"},
        )

    runtime = CanonicalRecordingRuntime()
    control_plane = HarnessControlPlane(
        event_port=_durable_port(runtime),
        worker_registry={"collect": worker},
        verify_gates=(gate,),
    )
    first_wait = control_plane.run(
        HarnessRunSpec(
            run_id="run-replan-approval",
            workflow=HarnessWorkflowSpec(
                workflow_id="replan-approval",
                steps=(
                    HarnessStepSpec(
                        step_id="collect",
                        worker_type="llm",
                        output_key="candidate",
                        metadata={"approval_required": True},
                    ),
                ),
                entry_step_id="collect",
            ),
        )
    )

    second_wait = control_plane.resume_after_approval(
        first_wait.state,
        approved=True,
    )

    assert second_wait.state.status == HarnessRunStatus.WAITING_APPROVAL
    assert worker_calls == 2
    dispatch_decisions = [
        event
        for event in runtime.events
        if _is_graph_decision_event(
            event,
            HarnessGraphDecisionType.DISPATCH_ACTIVITY,
        )
    ]
    wait_decisions = [
        event
        for event in runtime.events
        if _is_graph_decision_event(
            event,
            HarnessGraphDecisionType.WAIT_NODE,
            reason_code="harness_approval_required",
        )
    ]
    approval_events = [
        event
        for event in runtime.events
        if _is_graph_observation_event(
            event,
            HarnessGraphObservationType.WAIT_CAUSE,
        )
    ]
    assert [_graph_decision(event)["attempt"] for event in dispatch_decisions] == [1, 2]
    assert [_graph_decision(event)["attempt"] for event in wait_decisions] == [1, 2]
    assert [_graph_observation(event)["attempt"] for event in approval_events] == [1]
    second_dispatch_projection = _causal_graph_projection(
        runtime.events,
        dispatch_decisions[-1],
    )
    assert (
        second_dispatch_projection.stream_sequence < wait_decisions[-1].stream_sequence
    )

    completed = control_plane.resume_after_approval(
        second_wait.state,
        approved=True,
    )

    assert completed.state.status == HarnessRunStatus.SUCCEEDED
    assert gate.calls == 2
    assert worker_calls == 2
    approval_events = [
        event
        for event in runtime.events
        if _is_graph_observation_event(
            event,
            HarnessGraphObservationType.WAIT_CAUSE,
        )
    ]
    assert [_graph_observation(event)["attempt"] for event in approval_events] == [1, 2]


def test_approval_cancel_is_durable_before_cancelled_projection() -> None:
    runtime = CanonicalRecordingRuntime()
    port = _durable_port(runtime)
    control_plane = HarnessControlPlane(
        event_port=port,
        worker_registry={
            "collect": lambda task: HarnessWorkerResult(status="succeeded")
        },
    )
    waiting = control_plane.run(_run_spec("run-cancel", approval_required=True))
    before_cancel = len(runtime.events)

    cancelled = control_plane.resume_after_approval(waiting.state, approved=False)

    assert cancelled.state.status == HarnessRunStatus.CANCELLED
    cancel_events = runtime.events[before_cancel:]
    approval_event = cancel_events[0]
    assert approval_event.event_type == HARNESS_GRAPH_OBSERVATION_EVENT_TYPE
    approval = _graph_observation(approval_event)
    assert approval["observation_type"] == HarnessGraphObservationType.WAIT_CAUSE.value
    assert approval["payload"]["cause_kind"] == "approval"
    assert approval["payload"]["record"]["approved"] is False
    approval_projection = _causal_graph_projection(
        runtime.events,
        approval_event,
    )
    cancel_decision = next(
        event
        for event in cancel_events
        if _is_graph_decision_event(
            event,
            HarnessGraphDecisionType.COMPLETE_RUN,
            reason_code="approval_cancelled",
        )
    )
    cancel_projection = _causal_graph_projection(runtime.events, cancel_decision)
    assert (
        approval_event.stream_sequence
        < approval_projection.stream_sequence
        < cancel_decision.stream_sequence
        < cancel_projection.stream_sequence
    )
    terminal = _graph_projection_state(cancel_projection)
    assert terminal["lifecycle"] == RunLifecycle.COMPLETED.value
    assert terminal["outcome"] == RunOutcome.CANCELLED.value
    assert terminal["terminal_reason_code"] == "approval_cancelled"


def test_approval_resume_store_failure_leaves_input_state_unchanged() -> None:
    runtime = CanonicalRecordingRuntime()
    port = _durable_port(runtime)
    control_plane = HarnessControlPlane(
        event_port=port,
        worker_registry={
            "collect": lambda task: HarnessWorkerResult(status="succeeded")
        },
    )
    waiting = control_plane.run(_run_spec("run-resume-failure", approval_required=True))
    state = waiting.state
    before = port.recover_graph("run-resume-failure")
    runtime.fail_before = lambda request: _is_graph_observation_request(
        request,
        HarnessGraphObservationType.WAIT_CAUSE,
    )

    with pytest.raises(EventStoreUnavailableError):
        control_plane.resume_after_approval(state, approved=True)

    assert state.status == HarnessRunStatus.WAITING_APPROVAL
    assert port.recover_graph("run-resume-failure") == before
    assert before.pending_observations == ()


def test_approval_resume_rejects_a_supplied_state_that_conflicts_with_history() -> None:
    runtime = CanonicalRecordingRuntime()
    port = _durable_port(runtime)
    control_plane = HarnessControlPlane(
        event_port=port,
        worker_registry={
            "collect": lambda task: HarnessWorkerResult(status="succeeded")
        },
    )
    waiting = control_plane.run(
        _run_spec("run-resume-preflight", approval_required=True)
    )
    step_id = waiting.state.current_step_id
    assert step_id is not None
    unresolved_steps = tuple(
        replace(step, metadata={"worker_result_ref": "sha256:" + "1" * 64})
        if step.step_id == step_id
        else step
        for step in waiting.state.step_states
    )
    unresolved = replace(waiting.state, step_states=unresolved_steps)
    before = len(runtime.events)

    with pytest.raises(
        EventReplayMismatchError, match="does not match durable Graph history"
    ):
        control_plane.resume_after_approval(unresolved, approved=True)

    assert len(runtime.events) == before
    assert unresolved.status == HarnessRunStatus.WAITING_APPROVAL


def test_adapter_rejects_conflicting_duplicate_business_context() -> None:
    adapter = HarnessEventCanonicalAdapter()
    event = HarnessEvent(
        event_type=HarnessEventType.DECISION_RECORDED,
        run_id="run-authority",
        payload={
            "decision_type": "complete_run",
            "run_id": "another-run",
            "payload": {},
            "decided_by": "harness",
            "decided_at": "2026-07-15T08:00:00Z",
        },
        occurred_at=NOW,
    )

    with pytest.raises(HarnessValidationError, match="run_id conflicts"):
        adapter.to_publish_request(event)


def test_adapter_rejects_conflicting_duplicate_time_and_none_step_text() -> None:
    adapter = HarnessEventCanonicalAdapter()
    with pytest.raises(HarnessValidationError, match="occurred_at conflicts"):
        adapter.to_publish_request(
            HarnessEvent(
                event_type=HarnessEventType.PHASE_RECORDED,
                run_id="run-time-authority",
                step_id="collect",
                payload={
                    "phase": "plan",
                    "boundary": "entry",
                    "step_id": "collect",
                    "input_refs": [],
                    "output_refs": [],
                    "gate_results": [],
                    "metadata": {},
                    "occurred_at": "1999-01-01T00:00:00Z",
                },
                occurred_at=NOW,
            )
        )

    with pytest.raises(HarnessValidationError, match="step_id conflicts"):
        adapter.to_publish_request(
            HarnessEvent(
                event_type=HarnessEventType.RUN_STATE_CHANGED,
                run_id="run-step-authority",
                payload={"status": "running", "step_id": "None"},
                occurred_at=NOW,
            )
        )


def test_adapter_rejects_unbounded_legacy_trace_value_before_runtime() -> None:
    runtime = CanonicalRecordingRuntime()
    port = _durable_port(runtime)

    with pytest.raises(HarnessValidationError, match="trace_id has an unsafe format"):
        port.record(
            HarnessEvent(
                event_type=HarnessEventType.RUN_CREATED,
                run_id="run-trace-secret",
                trace_id="sk-trace-secret",
                occurred_at=NOW,
            )
        )

    assert runtime.attempts == []
    assert runtime.events == []


@pytest.mark.parametrize(
    "run_id",
    (
        "..",
        "../escape",
        "/absolute",
        r"C:\absolute",
        r"C:drive-relative",
        r"\\server\share",
        r"\\?\C:\device",
        "run:alternate-stream",
        "CON",
        "LPT1.txt",
    ),
)
def test_unsafe_run_id_fails_before_runtime_or_stream_derivation(run_id: str) -> None:
    runtime = CanonicalRecordingRuntime()
    port = _durable_port(runtime)

    with pytest.raises(ValueError):
        port.record(
            HarnessEvent(
                event_type=HarnessEventType.RUN_CREATED,
                run_id=run_id,
                occurred_at=NOW,
            )
        )

    assert runtime.attempts == []
    assert runtime.events == []
    assert port.events == []


def test_retry_and_terminal_failure_decisions_precede_graph_projection() -> None:
    runtime = CanonicalRecordingRuntime()
    port = _durable_port(runtime)
    workflow = HarnessWorkflowSpec(
        workflow_id="retry-order",
        steps=(
            HarnessStepSpec(
                step_id="collect",
                worker_type="llm",
                retry_policy=HarnessRetryPolicy(
                    max_attempts=2, retry_on_statuses=("failed",)
                ),
            ),
        ),
        entry_step_id="collect",
    )
    result = HarnessControlPlane(
        event_port=port,
        worker_registry={
            "collect": (
                HarnessWorkerResult(status="failed", error="first"),
                HarnessWorkerResult(status="failed", error="second"),
            )
        },
    ).run(HarnessRunSpec(run_id="run-retry-order", workflow=workflow))

    assert result.state.status == HarnessRunStatus.FAILED
    retry_decision = next(
        event
        for event in runtime.events
        if _is_graph_decision_event(
            event,
            HarnessGraphDecisionType.RETRY_NODE,
            reason_code="worker_failure_retry",
        )
    )
    retry_projection = _causal_graph_projection(runtime.events, retry_decision)
    retry_state = _graph_projection_state(retry_projection)
    assert retry_state["node_instances"][0]["step_status"] == "retrying"

    failure_decision = next(
        event
        for event in runtime.events
        if _is_graph_decision_event(
            event,
            HarnessGraphDecisionType.FAIL_NODE,
            reason_code="worker_failure_terminal",
        )
    )
    failure_projection = _causal_graph_projection(runtime.events, failure_decision)
    assert (
        _graph_projection_state(failure_projection)["node_instances"][0]["step_status"]
        == "failed"
    )

    terminal_decision = next(
        event
        for event in runtime.events
        if _is_graph_decision_event(
            event,
            HarnessGraphDecisionType.COMPLETE_RUN,
            reason_code="graph_terminal_failure",
        )
    )
    terminal_projection = _causal_graph_projection(runtime.events, terminal_decision)
    terminal_state = _graph_projection_state(terminal_projection)
    assert terminal_state["lifecycle"] == RunLifecycle.COMPLETED.value
    assert terminal_state["outcome"] == RunOutcome.FAILED.value
    assert (
        retry_decision.stream_sequence
        < retry_projection.stream_sequence
        < failure_decision.stream_sequence
        < failure_projection.stream_sequence
        < terminal_decision.stream_sequence
        < terminal_projection.stream_sequence
    )


def test_route_to_repair_and_budget_halt_use_durable_graph_decisions() -> None:
    repair_runtime = CanonicalRecordingRuntime()
    repair_port = _durable_port(repair_runtime)
    repair_workflow = HarnessWorkflowSpec(
        workflow_id="repair-order",
        steps=(
            HarnessStepSpec(
                step_id="draft",
                worker_type="llm",
                retry_policy=HarnessRetryPolicy(repair_step_id="repair"),
                metadata={"output_schema": {"required": ["title"]}},
            ),
            HarnessStepSpec(step_id="repair", worker_type="llm"),
        ),
        entry_step_id="draft",
    )
    HarnessControlPlane(
        event_port=repair_port,
        worker_registry={
            "draft": lambda task: HarnessWorkerResult(
                status="succeeded", output={"body": "missing"}
            ),
            "repair": lambda task: HarnessWorkerResult(
                status="succeeded", output={"title": "fixed"}
            ),
        },
    ).run(HarnessRunSpec(run_id="run-repair-order", workflow=repair_workflow))
    repair_decision = next(
        event
        for event in repair_runtime.events
        if _is_graph_decision_event(
            event,
            HarnessGraphDecisionType.ROUTE_TO_REPAIR,
        )
    )
    repair_projection = _causal_graph_projection(
        repair_runtime.events,
        repair_decision,
    )
    assert repair_decision.stream_sequence < repair_projection.stream_sequence
    assert _graph_decision(repair_decision)["target_node_ids"] == ["repair"]
    repair_state = _graph_projection_state(repair_projection)
    draft_node = next(
        node
        for node in repair_state["node_instances"]
        if node["identity"]["node_id"] == "draft"
    )
    assert draft_node["step_status"] == "failed"
    repair_activation = next(
        event
        for event in repair_runtime.events
        if _is_graph_decision_event(
            event,
            HarnessGraphDecisionType.ACTIVATE_NODE,
            node_id="repair",
        )
    )
    assert repair_projection.stream_sequence < repair_activation.stream_sequence

    halt_runtime = CanonicalRecordingRuntime()
    halt_port = _durable_port(halt_runtime)
    halted = HarnessControlPlane(
        event_port=halt_port,
        worker_registry={
            "collect": lambda task: HarnessWorkerResult(status="succeeded")
        },
    ).run(
        HarnessRunSpec(
            run_id="run-budget-halt",
            workflow=_run_spec("ignored").workflow,
            budget=HarnessBudget(
                max_turns=2,
                max_replans=0,
                max_retries_per_step=0,
                max_worker_calls=10,
            ),
        )
    )
    assert halted.state.status == HarnessRunStatus.HALTED
    budget_decision = next(
        event
        for event in halt_runtime.events
        if _is_graph_decision_event(
            event,
            HarnessGraphDecisionType.HALT_RUN,
        )
    )
    budget_projection = _causal_graph_projection(
        halt_runtime.events,
        budget_decision,
    )
    budget_state = _graph_projection_state(budget_projection)
    assert budget_decision.stream_sequence < budget_projection.stream_sequence
    assert budget_state["lifecycle"] == RunLifecycle.HALTED.value
    assert (
        budget_state["terminal_reason_code"]
        == _graph_decision(budget_decision)["reason_code"]
    )


def test_replan_decision_commits_before_replanning_projection() -> None:
    runtime = CanonicalRecordingRuntime()
    port = _durable_port(runtime)
    workflow = HarnessWorkflowSpec(
        workflow_id="replan-order",
        steps=(
            HarnessStepSpec(
                step_id="draft",
                worker_type="llm",
                metadata={"output_schema": {"required": ["title"]}},
            ),
        ),
        entry_step_id="draft",
    )
    HarnessControlPlane(
        event_port=port,
        worker_registry={
            "draft": lambda task: HarnessWorkerResult(
                status="succeeded", output={"body": "missing"}
            )
        },
    ).run(
        HarnessRunSpec(
            run_id="run-replan-order",
            workflow=workflow,
            budget=HarnessBudget(
                max_turns=20,
                max_replans=1,
                max_retries_per_step=0,
                max_worker_calls=10,
            ),
        )
    )

    replan_decision = next(
        event
        for event in runtime.events
        if _is_graph_decision_event(
            event,
            HarnessGraphDecisionType.REPLAN_NODE,
        )
    )
    replan_projection = _causal_graph_projection(runtime.events, replan_decision)
    replan_state = _graph_projection_state(replan_projection)
    assert replan_state["node_instances"][0]["step_status"] == "replanning"
    assert _budget_used(replan_state, "replans") == 1

    phase_decision = next(
        event
        for event in runtime.events
        if _is_graph_decision_event(
            event,
            HarnessGraphDecisionType.ENTER_STEP_PHASE,
            reason_code="controlled_replan",
        )
    )
    phase_projection = _causal_graph_projection(runtime.events, phase_decision)
    phase_state = _graph_projection_state(phase_projection)
    assert _graph_decision(phase_decision)["payload"]["phase"] == "plan"
    assert phase_state["node_instances"][0]["step_status"] == "planning"
    entry_event = next(
        event
        for event in runtime.events
        if event.stream_sequence > phase_projection.stream_sequence
        and event.event_type == HarnessEventType.PHASE_RECORDED
        and event.payload.get("phase") == "plan"
        and event.payload.get("boundary") == "entry"
    )
    exit_event = next(
        event
        for event in runtime.events
        if event.stream_sequence > entry_event.stream_sequence
        and event.event_type == HarnessEventType.PHASE_RECORDED
        and event.payload.get("phase") == "plan"
        and event.payload.get("boundary") == "exit"
    )
    assert (
        replan_decision.stream_sequence
        < replan_projection.stream_sequence
        < phase_decision.stream_sequence
        < phase_projection.stream_sequence
        < entry_event.stream_sequence
        < exit_event.stream_sequence
    )


def _graph_commit(event: StoredEvent) -> dict:
    assert event.payload is not None
    commit = event.payload.get("commit")
    assert isinstance(commit, Mapping)
    thawed = thaw_canonical_json(commit)
    assert isinstance(thawed, dict)
    if "state" not in thawed and isinstance(thawed.get("state_summary"), Mapping):
        thawed["state"] = thawed["state_summary"]
    return thawed


def _request_graph_commit(request: EventPublishRequest) -> dict | None:
    if request.payload is None:
        return None
    commit = request.payload.get("commit")
    if not isinstance(commit, Mapping):
        return None
    thawed = thaw_canonical_json(commit)
    assert isinstance(thawed, dict)
    return thawed


def _graph_decision(event: StoredEvent) -> dict:
    decision = _graph_commit(event).get("decision")
    assert isinstance(decision, dict)
    return decision


def _graph_observation(event: StoredEvent) -> dict:
    observation = _graph_commit(event).get("observation")
    assert isinstance(observation, dict)
    return observation


def _graph_projection_state(event: StoredEvent) -> dict:
    state = _graph_commit(event).get("state")
    assert isinstance(state, dict)
    return state


def _is_graph_decision_event(
    event: StoredEvent,
    decision_type: HarnessGraphDecisionType,
    *,
    node_id: str | None = None,
    reason_code: str | None = None,
) -> bool:
    if event.event_type != HARNESS_GRAPH_DECISION_EVENT_TYPE:
        return False
    decision = _graph_decision(event)
    return (
        decision.get("decision_type") == decision_type.value
        and (node_id is None or decision.get("node_id") == node_id)
        and (reason_code is None or decision.get("reason_code") == reason_code)
    )


def _is_graph_decision_request(
    request: EventPublishRequest,
    decision_type: HarnessGraphDecisionType,
    *,
    node_id: str | None = None,
    reason_code: str | None = None,
) -> bool:
    if request.event_type != HARNESS_GRAPH_DECISION_EVENT_TYPE:
        return False
    commit = _request_graph_commit(request)
    if commit is None:
        return False
    decision = commit.get("decision")
    if not isinstance(decision, dict):
        return False
    return (
        decision.get("decision_type") == decision_type.value
        and (node_id is None or decision.get("node_id") == node_id)
        and (reason_code is None or decision.get("reason_code") == reason_code)
    )


def _is_graph_observation_event(
    event: StoredEvent,
    observation_type: HarnessGraphObservationType,
) -> bool:
    return (
        event.event_type == HARNESS_GRAPH_OBSERVATION_EVENT_TYPE
        and _graph_observation(event).get("observation_type") == observation_type.value
    )


def _is_graph_observation_request(
    request: EventPublishRequest,
    observation_type: HarnessGraphObservationType,
) -> bool:
    if request.event_type != HARNESS_GRAPH_OBSERVATION_EVENT_TYPE:
        return False
    commit = _request_graph_commit(request)
    if commit is None:
        return False
    observation = commit.get("observation")
    return isinstance(observation, dict) and (
        observation.get("observation_type") == observation_type.value
    )


def _causal_graph_projection(
    events: list[StoredEvent],
    cause_event: StoredEvent,
) -> StoredEvent:
    if cause_event.event_type == HARNESS_GRAPH_DECISION_EVENT_TYPE:
        cause_checksum = _graph_decision(cause_event)["decision_checksum"]
    elif cause_event.event_type == HARNESS_GRAPH_OBSERVATION_EVENT_TYPE:
        cause_checksum = _graph_observation(cause_event)["observation_checksum"]
    else:
        raise AssertionError("unsupported Graph projection cause")
    return next(
        event
        for event in events
        if event.event_type == HARNESS_GRAPH_PROJECTION_EVENT_TYPE
        and event.stream_sequence > cause_event.stream_sequence
        and _graph_commit(event).get("cause_checksum") == cause_checksum
    )


def _budget_used(state: dict, budget_name: str) -> int:
    counters = state["budgets"]["counters"]
    return next(
        int(counter["used"]) for counter in counters if counter["name"] == budget_name
    )


def _default_worker_registry() -> dict[str, Callable[[dict], HarnessWorkerResult]]:
    return {
        "collect": lambda task: HarnessWorkerResult(
            status="succeeded",
            output=dict(task),
        )
    }


def _run_spec(run_id: str, *, approval_required: bool = False) -> HarnessRunSpec:
    return HarnessRunSpec(
        run_id=run_id,
        workflow=HarnessWorkflowSpec(
            workflow_id="durable-boundary",
            steps=(
                HarnessStepSpec(
                    step_id="collect",
                    worker_type="llm",
                    metadata={"approval_required": approval_required},
                ),
            ),
            entry_step_id="collect",
        ),
    )


def _event_index(
    events: list[StoredEvent],
    predicate: Callable[[StoredEvent], bool],
) -> int:
    return next(index for index, event in enumerate(events) if predicate(event))
