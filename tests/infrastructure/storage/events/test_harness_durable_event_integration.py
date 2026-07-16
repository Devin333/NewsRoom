from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from framework.events import (
    PayloadReference,
    StoredEvent,
    canonical_json_bytes,
    thaw_canonical_json,
)
from framework.events.errors import EventIncompleteHistoryError, EventStoreCorruptionError
from framework.events.runtime.activities import (
    REPLAY_ACTIVITY_RECORD_CONTENT_TYPE,
    RecordedActivityPayloadWrite,
    RecordedActivityWrite,
    ReplayActivityRecord,
    ReplayActivityRecordingConflictError,
    ReplayActivityStatus,
)
from framework.events.runtime.models import (
    ReplayMode,
    ReplayStartRequest,
    StreamReadRequest,
)
from framework.events.runtime.publisher import EventRuntime
from framework.events.runtime.replay_engine import (
    ReplayHistorySchemaError,
    ReplayReducerRegistration,
    ReplayReducerRegistry,
)
from framework.events.runtime.activities import ReplayActivityHandlerVersion
from framework.events.schema import (
    REQUIRED_SECURE_PAYLOAD_CAPABILITIES,
    EventSecurityProjector,
    SecurePayloadValidation,
    SecurityClassification,
    default_event_schema_catalog,
)
from framework.harness import (
    DurableHarnessTransitionPort,
    HarnessEventCanonicalAdapter,
    HarnessControlPlane,
    HarnessRunSpec,
    HarnessStepSpec,
    HarnessWorkerResult,
    HarnessWorkflowSpec,
)
from framework.harness.control_plane.replay_history import (
    build_harness_history_verifier,
)
from framework.shared.json import stable_json_dumps
from infrastructure.storage.events.sqlite import SQLiteEventStore
from infrastructure.storage.events.factory import DurableEventStorage
from infrastructure.storage.events.replay_checkpoints import (
    SQLiteReplayCheckpointStore,
)


class _RecordedActivityStore:
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
        if existing.recorded_ref != accepted_ref or existing.record.activity != record.activity:
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


def _activity_store(_tmp_path) -> _RecordedActivityStore:
    return _RecordedActivityStore()


class _MissingTerminalPayloadStore:
    def __init__(self, delegate) -> None:
        self.delegate = delegate

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    def get_payload(self, reference, *, tenant_id):
        del reference, tenant_id
        raise LookupError("recorded activity terminal payload is missing")


class _TamperingReader:
    def __init__(self, store, transform):
        self.store = store
        self.transform = transform

    def get_event(self, event_id, *, tenant_id=None):
        event = self.store.get_event(event_id, tenant_id=tenant_id)
        return None if event is None else self.transform(event)

    def read_stream(self, request):
        page = self.store.read_stream(request)
        return replace(
            page,
            events=tuple(self.transform(event) for event in page.events),
        )

    def get_stream_high_watermark(self, stream_id, *, tenant_id=None):
        return self.store.get_stream_high_watermark(stream_id, tenant_id=tenant_id)

def test_harness_without_secure_activity_store_fails_before_worker(tmp_path) -> None:
    worker_calls = 0

    def worker(task):
        nonlocal worker_calls
        worker_calls += 1
        return HarnessWorkerResult(status="succeeded")

    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    runtime = EventRuntime(
        store=store,
        schema_catalog=default_event_schema_catalog(),
    )
    event_port = DurableHarnessTransitionPort(runtime, store)
    workflow = HarnessWorkflowSpec(
        workflow_id="durable-integration",
        steps=(HarnessStepSpec(step_id="collect", worker_type="llm"),),
        entry_step_id="collect",
    )

    with pytest.raises(EventIncompleteHistoryError, match="recorded activity store"):
        HarnessControlPlane(
            event_port=event_port,
            worker_registry={"collect": worker},
        ).run(HarnessRunSpec(run_id="run-no-secure-store", workflow=workflow))

    assert worker_calls == 0


def test_harness_run_commits_through_default_catalog_and_sqlite_without_raw_worker_data(
    tmp_path,
) -> None:
    secret = "sk-harness-sqlite-integration-secret"
    secure_store = _activity_store(tmp_path)
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    runtime = EventRuntime(
        store=store,
        schema_catalog=default_event_schema_catalog(),
        security_projector=EventSecurityProjector(
            secure_payload_store=secure_store,
        ),
    )
    event_port = DurableHarnessTransitionPort(
        runtime,
        store,
        secure_activity_store=secure_store,
        adapter=HarnessEventCanonicalAdapter(
            tenant_id="tenant-test",
            security_classification=SecurityClassification.INTERNAL,
        ),
    )
    workflow = HarnessWorkflowSpec(
        workflow_id="durable-integration",
        steps=(HarnessStepSpec(step_id="collect", worker_type="llm"),),
        entry_step_id="collect",
    )

    result = HarnessControlPlane(
        event_port=event_port,
        worker_registry={
            "collect": lambda task: HarnessWorkerResult(
                status="succeeded",
                output={"answer": secret},
                diagnostics={"provider_message": secret},
            )
        },
    ).run(HarnessRunSpec(run_id="run-real-sqlite", workflow=workflow))

    assert result.succeeded is True
    page = store.read_stream(
        StreamReadRequest(
            stream_id="run:run-real-sqlite",
            limit=100,
            tenant_id="tenant-test",
        )
    )
    assert page.events
    assert [event.stream_sequence for event in page.events] == list(
        range(1, len(page.events) + 1)
    )
    assert secret not in stable_json_dumps([event.to_dict() for event in page.events])
    activity_write = next(iter(secure_store.records.values()))
    assert activity_write.record.outcome.output_ref is not None
    assert len(
        {
            activity_write.record.activity.input_ref.uri,
            activity_write.record.outcome.output_ref.uri,
            activity_write.recorded_ref.uri,
        }
    ) == 3


def test_sqlite_harness_history_verification_uses_recorded_decision_commands(
    tmp_path,
) -> None:
    secure_store = _activity_store(tmp_path)
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    catalog = default_event_schema_catalog()
    runtime = EventRuntime(
        store=store,
        schema_catalog=catalog,
        security_projector=EventSecurityProjector(
            secure_payload_store=secure_store,
        ),
    )
    workflow = HarnessWorkflowSpec(
        workflow_id="durable-history",
        steps=(HarnessStepSpec(step_id="collect", worker_type="llm"),),
        entry_step_id="collect",
        metadata={"version": "1"},
    )
    worker_calls = 0

    def worker(_task):
        nonlocal worker_calls
        worker_calls += 1
        return HarnessWorkerResult(status="succeeded")

    HarnessControlPlane(
        event_port=DurableHarnessTransitionPort(
            runtime,
            store,
            secure_activity_store=secure_store,
            adapter=HarnessEventCanonicalAdapter(tenant_id="tenant-test"),
        ),
        worker_registry={"collect": worker},
    ).run(HarnessRunSpec(run_id="run-history-verify", workflow=workflow))
    storage = DurableEventStorage(
        event_store=store,
        replay_checkpoint_store=SQLiteReplayCheckpointStore(
            tmp_path / "events.sqlite3"
        ),
        event_runtime=runtime,
        schema_catalog=catalog,
    )
    verifier = build_harness_history_verifier(
        workflow_id=workflow.workflow_id,
        workflow_version="1",
        secure_activity_store=secure_store,
        activity_versions=(
            ReplayActivityHandlerVersion(
                "llm",
                "newsroom.harness-worker-activity/v1",
                "1",
            ),
        ),
    )

    engine = storage.create_replay_engine(
        reducers=ReplayReducerRegistry(),
        history_verifier=verifier,
        clock=lambda: datetime(2026, 7, 16, 12, 0, tzinfo=UTC),
    )
    result = engine.verify_history(
        ReplayStartRequest(
            replay_id="verify-harness-history",
            mode=ReplayMode.VERIFY_HISTORY,
            source_stream_id="run:run-history-verify",
            requested_at=datetime(2026, 7, 16, 12, 0, tzinfo=UTC),
            tenant_id="tenant-test",
        )
    )

    assert result.report.status.value == "succeeded"
    assert worker_calls == 1
    assert result.report.to_sequence == store.get_stream_high_watermark(
        "run:run-history-verify",
        tenant_id="tenant-test",
    )


def test_approval_restart_recovers_secure_worker_result_without_reinvocation(
    tmp_path,
) -> None:
    worker_calls = 0

    def worker(task):
        nonlocal worker_calls
        worker_calls += 1
        return HarnessWorkerResult(
            status="succeeded",
            output={"candidate": "ready"},
        )

    secure_store = _activity_store(tmp_path)
    store = SQLiteEventStore(tmp_path / "events.sqlite3")

    def build_port():
        runtime = EventRuntime(
            store=store,
            schema_catalog=default_event_schema_catalog(),
            security_projector=EventSecurityProjector(
                secure_payload_store=secure_store,
            ),
        )
        return DurableHarnessTransitionPort(
            runtime,
            store,
            secure_activity_store=secure_store,
            adapter=HarnessEventCanonicalAdapter(tenant_id="tenant-test"),
        )

    run_spec = HarnessRunSpec(
        run_id="run-approval-restart",
        workflow=HarnessWorkflowSpec(
            workflow_id="approval-restart",
            steps=(
                HarnessStepSpec(
                    step_id="collect",
                    worker_type="llm",
                    metadata={"approval_required": True},
                ),
            ),
            entry_step_id="collect",
            metadata={"version": "1"},
        ),
    )
    waiting = HarnessControlPlane(
        event_port=build_port(),
        worker_registry={"collect": worker},
    ).run(run_spec)
    assert waiting.state.status.value == "waiting_approval"

    resumed = HarnessControlPlane(
        event_port=build_port(),
        worker_registry={"collect": worker},
    ).resume_after_approval(run_spec, approved=True)

    assert resumed.state.status.value == "succeeded"
    assert worker_calls == 1


@pytest.mark.parametrize(
    ("worker_status", "run_status"),
    (
        ("failed", "failed"),
        ("blocked", "blocked"),
        ("waiting_approval", "waiting_approval"),
    ),
)
def test_recovery_reuses_recorded_non_success_worker_outcome(
    tmp_path,
    worker_status: str,
    run_status: str,
) -> None:
    activity_store = _activity_store(tmp_path)
    event_store = SQLiteEventStore(tmp_path / "events.sqlite3")
    runtime = EventRuntime(
        store=event_store,
        schema_catalog=default_event_schema_catalog(),
        security_projector=EventSecurityProjector(
            secure_payload_store=activity_store,
        ),
    )

    def build_port():
        return DurableHarnessTransitionPort(
            runtime,
            event_store,
            secure_activity_store=activity_store,
            adapter=HarnessEventCanonicalAdapter(tenant_id="tenant-test"),
        )

    provider_calls = 0

    def provider(_task):
        nonlocal provider_calls
        provider_calls += 1
        return HarnessWorkerResult(
            status=worker_status,
            error=f"recorded {worker_status}",
        )

    run_spec = HarnessRunSpec(
        run_id=f"run-recorded-{worker_status}",
        workflow=HarnessWorkflowSpec(
            workflow_id="recorded-terminal-status",
            steps=(HarnessStepSpec(step_id="collect", worker_type="llm"),),
            entry_step_id="collect",
            metadata={"version": "1"},
        ),
    )
    initial = HarnessControlPlane(
        event_port=build_port(),
        worker_registry={"collect": provider},
    ).run(run_spec)
    recovered = HarnessControlPlane(
        event_port=build_port(),
        worker_registry={"collect": provider},
    ).recover_and_run(run_spec)

    assert initial.state.status.value == run_status
    assert recovered.state.status.value == run_status
    assert provider_calls == 1
    activity_write = next(iter(activity_store.records.values()))
    outcome = activity_write.record.outcome
    assert outcome.error_class == f"harness_worker_{worker_status}"
    assert outcome.error_ref is not None
    assert len(
        {
            activity_write.record.activity.input_ref.uri,
            outcome.error_ref.uri,
            activity_write.recorded_ref.uri,
        }
    ) == 3


def test_reference_only_activity_verifies_without_provider_but_rebuild_fails_closed(
    tmp_path,
) -> None:
    secure_store = _activity_store(tmp_path)
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    catalog = default_event_schema_catalog()
    runtime = EventRuntime(
        store=store,
        schema_catalog=catalog,
        security_projector=EventSecurityProjector(
            secure_payload_store=secure_store,
        ),
    )
    workflow = HarnessWorkflowSpec(
        workflow_id="reference-only-replay",
        steps=(HarnessStepSpec(step_id="collect", worker_type="llm"),),
        entry_step_id="collect",
        metadata={"version": "1"},
    )
    provider_calls = 0

    def provider(_task):
        nonlocal provider_calls
        provider_calls += 1
        return HarnessWorkerResult(status="succeeded", output={"answer": "recorded"})

    HarnessControlPlane(
        event_port=DurableHarnessTransitionPort(
            runtime,
            store,
            secure_activity_store=secure_store,
            adapter=HarnessEventCanonicalAdapter(tenant_id="tenant-test"),
        ),
        worker_registry={"collect": provider},
    ).run(HarnessRunSpec(run_id="run-reference-only", workflow=workflow))
    provider_calls_after_live_run = provider_calls
    storage = DurableEventStorage(
        event_store=store,
        replay_checkpoint_store=SQLiteReplayCheckpointStore(
            tmp_path / "events.sqlite3"
        ),
        event_runtime=runtime,
        schema_catalog=catalog,
    )
    verifier = build_harness_history_verifier(
        workflow_id=workflow.workflow_id,
        workflow_version="1",
        secure_activity_store=secure_store,
        activity_versions=(
            ReplayActivityHandlerVersion(
                "llm",
                "newsroom.harness-worker-activity/v1",
                "1",
            ),
        ),
    )
    engine = storage.create_replay_engine(
        reducers=ReplayReducerRegistry(),
        history_verifier=verifier,
        clock=lambda: datetime(2026, 7, 16, 12, 0, tzinfo=UTC),
    )

    verified = engine.verify_history(
        ReplayStartRequest(
            replay_id="verify-reference-only",
            mode=ReplayMode.VERIFY_HISTORY,
            source_stream_id="run:run-reference-only",
            requested_at=datetime(2026, 7, 16, 12, 0, tzinfo=UTC),
            tenant_id="tenant-test",
        )
    )

    assert verified.report.status.value == "succeeded"
    assert provider_calls == provider_calls_after_live_run == 1

    reducers = ReplayReducerRegistry()
    reducers.register(
        ReplayReducerRegistration(
            reducer_id="count-events",
            version="1",
            reducer=lambda state, event: {"count": state["count"] + 1},
            initial_state={"count": 0},
        )
    )
    rebuild_engine = storage.create_replay_engine(
        reducers=reducers,
        history_verifier=verifier,
        clock=lambda: datetime(2026, 7, 16, 12, 1, tzinfo=UTC),
    )
    with pytest.raises(ReplayHistorySchemaError) as caught:
        rebuild_engine.rebuild_state(
            ReplayStartRequest(
                replay_id="rebuild-reference-only",
                mode=ReplayMode.REBUILD_STATE,
                source_stream_id="run:run-reference-only",
                requested_at=datetime(2026, 7, 16, 12, 1, tzinfo=UTC),
                tenant_id="tenant-test",
            ),
            reducer_id="count-events",
            reducer_version="1",
        )
    assert "payload_unavailable" in str(caught.value)
    assert provider_calls == 1


def test_recovery_rejects_missing_terminal_payload_and_activity_binding_tamper(
    tmp_path,
) -> None:
    secure_store = _activity_store(tmp_path)
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    catalog = default_event_schema_catalog()
    runtime = EventRuntime(
        store=store,
        schema_catalog=catalog,
        security_projector=EventSecurityProjector(
            secure_payload_store=secure_store,
        ),
    )
    run_spec = HarnessRunSpec(
        run_id="run-binding-corruption",
        workflow=HarnessWorkflowSpec(
            workflow_id="binding-corruption",
            steps=(
                HarnessStepSpec(
                    step_id="collect",
                    worker_type="llm",
                    metadata={"approval_required": True},
                ),
            ),
            entry_step_id="collect",
            metadata={"version": "1"},
        ),
    )
    HarnessControlPlane(
        event_port=DurableHarnessTransitionPort(
            runtime,
            store,
            secure_activity_store=secure_store,
            adapter=HarnessEventCanonicalAdapter(tenant_id="tenant-test"),
        ),
        worker_registry={
            "collect": lambda _task: HarnessWorkerResult(status="succeeded")
        },
    ).run(run_spec)
    with pytest.raises(EventIncompleteHistoryError, match="result is unavailable"):
        HarnessControlPlane(
            event_port=DurableHarnessTransitionPort(
                runtime,
                store,
                secure_activity_store=_MissingTerminalPayloadStore(secure_store),
                adapter=HarnessEventCanonicalAdapter(tenant_id="tenant-test"),
            ),
        ).recover_and_run(run_spec)

    def tamper_result_ref(event: StoredEvent) -> StoredEvent:
        if event.event_type != "worker_result_recorded":
            return event
        reference = event.payload_ref
        assert reference is not None
        tampered_ref = PayloadReference(
            uri=f"{reference.uri}-tampered",
            expected_checksum=reference.expected_checksum,
            content_type=reference.content_type,
            size_bytes=reference.size_bytes,
        )
        return StoredEvent(
            candidate=replace(event.candidate, payload_ref=tampered_ref),
            observed_at=event.observed_at,
            stream_sequence=event.stream_sequence,
        )

    with pytest.raises(EventStoreCorruptionError):
        HarnessControlPlane(
            event_port=DurableHarnessTransitionPort(
                runtime,
                _TamperingReader(store, tamper_result_ref),
                secure_activity_store=secure_store,
                adapter=HarnessEventCanonicalAdapter(tenant_id="tenant-test"),
            ),
        ).recover_and_run(run_spec)

    def tamper_activity_extension(field_name: str):
        def transform(event: StoredEvent) -> StoredEvent:
            if event.event_type != "worker_result_recorded":
                return event
            extensions = thaw_canonical_json(event.extensions)
            activity_extension = extensions["harness_activity"]
            if field_name == "activity":
                activity_extension["activity"]["worker_version"] = "tampered"
            elif field_name == "status":
                activity_extension["status"] = "blocked"
            else:
                activity_extension["error_class"] = "harness_worker_blocked"
            return StoredEvent(
                candidate=replace(event.candidate, extensions=extensions),
                observed_at=event.observed_at,
                stream_sequence=event.stream_sequence,
            )

        return transform

    for field_name in ("activity", "status", "error_class"):
        with pytest.raises(EventStoreCorruptionError):
            HarnessControlPlane(
                event_port=DurableHarnessTransitionPort(
                    runtime,
                    _TamperingReader(
                        store,
                        tamper_activity_extension(field_name),
                    ),
                    secure_activity_store=secure_store,
                    adapter=HarnessEventCanonicalAdapter(tenant_id="tenant-test"),
                ),
            ).recover_and_run(run_spec)
