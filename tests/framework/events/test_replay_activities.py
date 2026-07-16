from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from framework.events.canonical import (
    PayloadReference,
    canonical_json_bytes,
    checksum_for,
)
from framework.events.runtime.activities import (
    REPLAY_ACTIVITY_RECORD_CONTENT_TYPE,
    ActivityRecorder,
    RecordedActivityPayloadWrite,
    RecordedActivityResolver,
    RecordedActivityWrite,
    ReplayActivityCorruptionError,
    ReplayActivityDescriptor,
    ReplayActivityHandlerVersion,
    ReplayActivityIncompleteError,
    ReplayActivityInputMismatchError,
    ReplayActivityKind,
    ReplayActivityMismatchError,
    ReplayActivityMissingError,
    ReplayActivityOutcome,
    ReplayActivityPayload,
    ReplayActivityPayloadRole,
    ReplayActivityRecord,
    ReplayActivityRecordingConflictError,
    ReplayActivityRegistry,
    ReplayActivityStatus,
    ReplayActivityTenantMismatchError,
    ReplayActivityVersionError,
)
from framework.events.schema.security import SecurityClassification


ACCEPTED_AT = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)
STARTED_AT = ACCEPTED_AT + timedelta(seconds=1)
COMPLETED_AT = STARTED_AT + timedelta(seconds=2)
CONTRACT_VERSION = "newsroom.activity/v1"
HANDLER_VERSION = "handler/3.2.1"


class _RecordedStore:
    def __init__(self, value: Any) -> None:
        self.value = value
        self.calls: list[tuple[PayloadReference, str | None]] = []

    def get_record(self, recorded_ref: PayloadReference, *, tenant_id: str | None):
        self.calls.append((recorded_ref, tenant_id))
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


def _ref(name: str, content: Any) -> PayloadReference:
    return PayloadReference(
        uri=f"secure-activity://tenant-a/{name}",
        expected_checksum=checksum_for(content),
        content_type="application/json",
        size_bytes=100,
    )


def _activity(
    kind: ReplayActivityKind = ReplayActivityKind.LLM,
    *,
    activity_id: str = "activity-1",
    tenant_id: str | None = "tenant-a",
    input_content: Any = None,
    contract_version: str = CONTRACT_VERSION,
    handler_version: str = HANDLER_VERSION,
    attempt: int = 1,
) -> ReplayActivityDescriptor:
    content = {"prompt": "accepted"} if input_content is None else input_content
    input_ref = _ref("input", content)
    return ReplayActivityDescriptor(
        activity_id=activity_id,
        activity_kind=kind,
        input_ref=input_ref,
        input_checksum=input_ref.expected_checksum,
        idempotency_key=f"idempotency:{activity_id}",
        attempt=attempt,
        contract_version=contract_version,
        handler_version=handler_version,
        accepted_at=ACCEPTED_AT,
        tenant_id=tenant_id,
        security_classification=SecurityClassification.CONFIDENTIAL,
    )


def _outcome(
    activity_id: str = "activity-1",
    *,
    status: ReplayActivityStatus = ReplayActivityStatus.SUCCEEDED,
) -> ReplayActivityOutcome:
    if status is ReplayActivityStatus.PENDING:
        return ReplayActivityOutcome(
            activity_id=activity_id,
            status=status,
            started_at=STARTED_AT,
        )
    if status is ReplayActivityStatus.FAILED:
        return ReplayActivityOutcome(
            activity_id=activity_id,
            status=status,
            started_at=STARTED_AT,
            completed_at=COMPLETED_AT,
            error_class="provider_timeout",
            error_ref=_ref("error", {"reason": "redacted"}),
        )
    output_ref = _ref("output", {"answer": "recorded"})
    return ReplayActivityOutcome(
        activity_id=activity_id,
        status=status,
        started_at=STARTED_AT,
        completed_at=COMPLETED_AT,
        output_ref=output_ref,
        output_checksum=output_ref.expected_checksum,
    )


def _record(
    kind: ReplayActivityKind = ReplayActivityKind.LLM,
    *,
    status: ReplayActivityStatus = ReplayActivityStatus.SUCCEEDED,
) -> ReplayActivityRecord:
    activity = _activity(kind)
    return ReplayActivityRecord(activity, _outcome(activity.activity_id, status=status))


def _registry(*versions: ReplayActivityHandlerVersion) -> ReplayActivityRegistry:
    registry = ReplayActivityRegistry()
    for version in versions or (
        ReplayActivityHandlerVersion(
            ReplayActivityKind.LLM,
            CONTRACT_VERSION,
            HANDLER_VERSION,
        ),
    ):
        registry.register(version)
    return registry


def _record_ref(record: ReplayActivityRecord) -> PayloadReference:
    return PayloadReference(
        uri="secure-activity://tenant-a/record/activity-1",
        expected_checksum=record.record_checksum,
        content_type="application/vnd.newsroom.replay-activity-record+json",
        size_bytes=500,
    )


def _payload_write(payload: ReplayActivityPayload) -> RecordedActivityPayloadWrite:
    return RecordedActivityPayloadWrite(
        payload=payload,
        payload_ref=PayloadReference(
            uri=(
                f"secure-activity://{payload.tenant_id or 'global'}/payload/"
                f"{payload.activity_id}/{payload.role.value}/"
                f"{payload.content_checksum.removeprefix('sha256:')}"
            ),
            expected_checksum=payload.content_checksum,
            content_type=payload.content_type,
            size_bytes=len(canonical_json_bytes(payload.content)),
        ),
    )


def _activity_write(record: ReplayActivityRecord) -> RecordedActivityWrite:
    return RecordedActivityWrite(
        record=record,
        recorded_ref=PayloadReference(
            uri=(
                f"secure-activity://{record.activity.tenant_id or 'global'}/record/"
                f"{record.activity.activity_id}/"
                f"{record.record_checksum.removeprefix('sha256:')}"
            ),
            expected_checksum=record.record_checksum,
            content_type=REPLAY_ACTIVITY_RECORD_CONTENT_TYPE,
            size_bytes=len(canonical_json_bytes(record.to_dict())),
        ),
    )


class _ActivityWriteStore:
    def __init__(self) -> None:
        self.payloads: dict[
            tuple[str, ReplayActivityPayloadRole],
            RecordedActivityPayloadWrite,
        ] = {}
        self.records: dict[str, RecordedActivityWrite] = {}
        self.calls: list[str] = []
        self.errors: dict[str, Exception] = {}
        self.payload_transform = None
        self.accept_transform = None
        self.complete_transform = None

    def put_payload(
        self,
        payload: ReplayActivityPayload,
        *,
        tenant_id: str | None,
        classification: SecurityClassification,
    ) -> RecordedActivityPayloadWrite:
        call = f"put_payload:{payload.role.value}"
        self.calls.append(call)
        self._raise_if_configured(call)
        if (
            tenant_id != payload.tenant_id
            or classification is not payload.security_classification
        ):
            raise ReplayActivityRecordingConflictError("payload scope conflict")
        key = (payload.activity_id, payload.role)
        existing = self.payloads.get(key)
        if existing is not None:
            if existing.payload != payload:
                raise ReplayActivityRecordingConflictError("payload identity collision")
            write = existing
        else:
            write = _payload_write(payload)
            self.payloads[key] = write
        if self.payload_transform is not None:
            return self.payload_transform(write)
        return write

    def accept_record(
        self,
        record: ReplayActivityRecord,
        *,
        tenant_id: str | None,
        classification: SecurityClassification,
    ) -> RecordedActivityWrite:
        self.calls.append("accept_record")
        self._raise_if_configured("accept_record")
        self._validate_scope(record, tenant_id, classification)
        existing = self.records.get(record.activity.activity_id)
        if existing is not None:
            if (
                existing.record.activity != record.activity
                or existing.record.outcome.started_at != record.outcome.started_at
            ):
                raise ReplayActivityRecordingConflictError(
                    "activity identity collision"
                )
            write = existing
        else:
            write = _activity_write(record)
            self.records[record.activity.activity_id] = write
        if self.accept_transform is not None:
            return self.accept_transform(write)
        return write

    def complete_record(
        self,
        accepted_ref: PayloadReference,
        record: ReplayActivityRecord,
        *,
        tenant_id: str | None,
        classification: SecurityClassification,
    ) -> RecordedActivityWrite:
        self.calls.append("complete_record")
        self._raise_if_configured("complete_record")
        self._validate_scope(record, tenant_id, classification)
        existing = self.records.get(record.activity.activity_id)
        if existing is None:
            raise ReplayActivityRecordingConflictError("activity is not accepted")
        if existing.record.outcome.status is not ReplayActivityStatus.PENDING:
            if existing.record != record:
                raise ReplayActivityRecordingConflictError("terminal outcome collision")
            write = existing
        else:
            if existing.recorded_ref != accepted_ref:
                raise ReplayActivityRecordingConflictError("stale accepted reference")
            if existing.record.activity != record.activity:
                raise ReplayActivityRecordingConflictError(
                    "activity descriptor collision"
                )
            write = _activity_write(record)
            self.records[record.activity.activity_id] = write
        if self.complete_transform is not None:
            return self.complete_transform(write)
        return write

    def get_record(
        self,
        recorded_ref: PayloadReference,
        *,
        tenant_id: str | None,
    ) -> ReplayActivityRecord | None:
        for write in self.records.values():
            if (
                write.recorded_ref == recorded_ref
                and write.record.activity.tenant_id == tenant_id
            ):
                return write.record
        return None

    def _raise_if_configured(self, call: str) -> None:
        error = self.errors.get(call)
        if error is not None:
            raise error

    @staticmethod
    def _validate_scope(
        record: ReplayActivityRecord,
        tenant_id: str | None,
        classification: SecurityClassification,
    ) -> None:
        if (
            tenant_id != record.activity.tenant_id
            or classification is not record.activity.security_classification
        ):
            raise ReplayActivityRecordingConflictError("record scope conflict")


def _accept_recording(
    store: _ActivityWriteStore,
    kind: ReplayActivityKind = ReplayActivityKind.LLM,
    **overrides: Any,
):
    values = {
        "activity_id": "recording-1",
        "activity_kind": kind,
        "input_value": {"prompt": "accepted"},
        "idempotency_key": "recording:1",
        "attempt": 1,
        "contract_version": CONTRACT_VERSION,
        "handler_version": HANDLER_VERSION,
        "accepted_at": ACCEPTED_AT,
        "started_at": STARTED_AT,
        "context": {"run_id": "run-1"},
        "tenant_id": "tenant-a",
        "security_classification": SecurityClassification.CONFIDENTIAL,
    }
    values.update(overrides)
    return ActivityRecorder(store).accept(**values)


@pytest.mark.parametrize("kind", tuple(ReplayActivityKind))
def test_activity_contract_covers_every_nondeterministic_kind(
    kind: ReplayActivityKind,
) -> None:
    activity = _activity(kind)
    outcome = _outcome()
    record = ReplayActivityRecord(activity, outcome)

    assert activity.activity_kind is kind
    assert activity.attempt == 1
    assert activity.input_checksum == activity.input_ref.expected_checksum
    assert outcome.output_checksum == outcome.output_ref.expected_checksum
    assert record.to_dict()["activity"]["activity_kind"] == kind.value
    assert ReplayActivityRecord.from_dict(record.to_dict()) == record


def test_activity_record_is_a_canonical_immutable_snapshot() -> None:
    source = _record().to_dict()
    parsed = ReplayActivityRecord.from_dict(source)
    serialized = parsed.to_dict()

    source["activity"]["input_ref"]["uri"] = "secure-activity://tenant-a/mutated"
    source["outcome"]["output_ref"]["uri"] = "secure-activity://tenant-a/mutated"
    source["outcome"]["status"] = "failed"

    assert parsed.to_dict() == serialized
    assert parsed.activity.input_ref.uri.endswith("/input")
    assert parsed.outcome.output_ref is not None
    assert parsed.outcome.output_ref.uri.endswith("/output")
    parsed.verify_integrity()


def test_activity_contract_normalizes_timestamps_and_records_scope_and_versions() -> (
    None
):
    plus_eight = timezone(timedelta(hours=8))
    input_ref = _ref("input", {"request": "accepted"})
    activity = ReplayActivityDescriptor(
        activity_id="clock-1",
        activity_kind=ReplayActivityKind.CLOCK,
        input_ref=input_ref,
        input_checksum=input_ref.expected_checksum,
        idempotency_key="clock:1",
        attempt=2,
        contract_version="clock-contract/2",
        handler_version="system-clock/1",
        accepted_at=datetime(2026, 7, 16, 16, 0, tzinfo=plus_eight),
        tenant_id="tenant-a",
        security_classification="restricted",
    )

    assert activity.accepted_at == ACCEPTED_AT
    assert activity.attempt == 2
    assert activity.pinned_version == ReplayActivityHandlerVersion(
        ReplayActivityKind.CLOCK,
        "clock-contract/2",
        "system-clock/1",
    )
    assert activity.security_classification is SecurityClassification.RESTRICTED


def test_activity_outcome_enforces_terminal_status_contracts() -> None:
    output_ref = _ref("output", {"answer": "recorded"})

    with pytest.raises(ValueError, match="pending activity"):
        ReplayActivityOutcome(
            "activity-1",
            ReplayActivityStatus.PENDING,
            STARTED_AT,
            completed_at=COMPLETED_AT,
        )
    with pytest.raises(ValueError, match="requires completed_at and output"):
        ReplayActivityOutcome(
            "activity-1",
            ReplayActivityStatus.SUCCEEDED,
            STARTED_AT,
            completed_at=COMPLETED_AT,
        )
    with pytest.raises(ValueError, match="requires completed_at and error_class"):
        ReplayActivityOutcome(
            "activity-1",
            ReplayActivityStatus.FAILED,
            STARTED_AT,
            completed_at=COMPLETED_AT,
        )
    with pytest.raises(ValueError, match="must match output_ref"):
        ReplayActivityOutcome(
            "activity-1",
            ReplayActivityStatus.SUCCEEDED,
            STARTED_AT,
            completed_at=COMPLETED_AT,
            output_ref=output_ref,
            output_checksum=checksum_for("different"),
        )


def test_activity_registry_resolves_exact_kind_contract_and_handler_version() -> None:
    v1 = ReplayActivityHandlerVersion(
        ReplayActivityKind.HTTP,
        "http-contract/1",
        "urllib-handler/1",
    )
    v2 = ReplayActivityHandlerVersion(
        ReplayActivityKind.HTTP,
        "http-contract/1",
        "urllib-handler/2",
    )
    registry = _registry(v2, v1)

    assert registry.resolve("http", "http-contract/1", "urllib-handler/1") == v1
    assert registry.versions() == (v1, v2)
    with pytest.raises(ReplayActivityVersionError, match="unregistered"):
        registry.resolve("http", "http-contract/2", "urllib-handler/2")
    with pytest.raises(ReplayActivityVersionError, match="duplicate"):
        registry.register(v1)


def test_recorded_resolver_returns_canonical_outcome_and_pinned_version_only() -> None:
    record = _record()
    recorded_ref = _record_ref(record)
    store = _RecordedStore(record.to_dict())
    resolver = RecordedActivityResolver(store, _registry())

    resolved = resolver.resolve(record.activity, recorded_ref)

    assert resolved.activity == record.activity
    assert resolved.outcome == record.outcome
    assert resolved.pinned_version == record.activity.pinned_version
    assert resolved.recorded_ref == recorded_ref
    assert store.calls == [(recorded_ref, "tenant-a")]
    assert not hasattr(resolver, "provider")
    assert not hasattr(resolver, "live_provider")


@pytest.mark.parametrize("stored", [None, LookupError("missing")])
def test_recorded_resolver_missing_history_fails_closed(stored: Any) -> None:
    record = _record()
    resolver = RecordedActivityResolver(_RecordedStore(stored), _registry())

    with pytest.raises(ReplayActivityMissingError):
        resolver.resolve(record.activity, _record_ref(record))


def test_recorded_resolver_rejects_pending_outcome() -> None:
    record = _record(status=ReplayActivityStatus.PENDING)
    resolver = RecordedActivityResolver(_RecordedStore(record), _registry())

    with pytest.raises(ReplayActivityIncompleteError):
        resolver.resolve(record.activity, _record_ref(record))


def test_recorded_resolver_returns_completed_failed_outcome() -> None:
    record = _record(status=ReplayActivityStatus.FAILED)
    resolver = RecordedActivityResolver(_RecordedStore(record), _registry())

    resolved = resolver.resolve(record.activity, _record_ref(record))

    assert resolved.activity == record.activity
    assert resolved.outcome == record.outcome
    assert resolved.outcome.status is ReplayActivityStatus.FAILED
    assert resolved.outcome.completed_at == COMPLETED_AT
    assert resolved.outcome.error_class == "provider_timeout"
    assert resolved.outcome.error_ref == record.outcome.error_ref


def test_recorded_resolver_rejects_corrupt_record_and_reference_checksums() -> None:
    record = _record()
    corrupted = record.to_dict()
    corrupted["outcome"]["output_ref"]["uri"] = "secure-activity://tenant-a/tampered"
    resolver = RecordedActivityResolver(_RecordedStore(corrupted), _registry())

    with pytest.raises(ReplayActivityCorruptionError, match="checksum"):
        resolver.resolve(record.activity, _record_ref(record))

    wrong_ref = replace(_record_ref(record), expected_checksum=checksum_for("wrong"))
    with pytest.raises(ReplayActivityCorruptionError, match="reference checksum"):
        RecordedActivityResolver(_RecordedStore(record), _registry()).resolve(
            record.activity,
            wrong_ref,
        )


def test_recorded_resolver_rejects_accepted_input_mismatch() -> None:
    record = _record()
    changed_input = _ref("input-changed", {"prompt": "changed"})
    expected = replace(
        record.activity,
        input_ref=changed_input,
        input_checksum=changed_input.expected_checksum,
    )
    resolver = RecordedActivityResolver(_RecordedStore(record), _registry())

    with pytest.raises(ReplayActivityInputMismatchError):
        resolver.resolve(expected, _record_ref(record))


@pytest.mark.parametrize(
    "expected",
    [
        replace(_activity(), tenant_id="tenant-b"),
        replace(
            _activity(),
            security_classification=SecurityClassification.RESTRICTED,
        ),
    ],
)
def test_recorded_resolver_rejects_tenant_or_classification_mismatch(
    expected: ReplayActivityDescriptor,
) -> None:
    record = _record()
    resolver = RecordedActivityResolver(_RecordedStore(record), _registry())

    with pytest.raises(ReplayActivityTenantMismatchError):
        resolver.resolve(expected, _record_ref(record))


def test_recorded_resolver_rejects_identity_attempt_and_idempotency_mismatch() -> None:
    record = _record()
    resolver = RecordedActivityResolver(_RecordedStore(record), _registry())

    with pytest.raises(ReplayActivityMismatchError, match="identity"):
        resolver.resolve(
            replace(record.activity, activity_id="different"),
            _record_ref(record),
        )
    with pytest.raises(ReplayActivityInputMismatchError):
        resolver.resolve(
            replace(record.activity, attempt=2),
            _record_ref(record),
        )
    with pytest.raises(ReplayActivityInputMismatchError):
        resolver.resolve(
            replace(record.activity, idempotency_key="different"),
            _record_ref(record),
        )


def test_recorded_resolver_rejects_missing_or_conflicting_versions_before_success() -> (
    None
):
    record = _record()
    expected_v2 = replace(
        record.activity,
        contract_version="newsroom.activity/v2",
        handler_version="handler/4",
    )
    v2 = expected_v2.pinned_version
    store = _RecordedStore(record)

    with pytest.raises(ReplayActivityVersionError, match="unregistered"):
        RecordedActivityResolver(store, ReplayActivityRegistry()).resolve(
            record.activity,
            _record_ref(record),
        )
    assert store.calls == []

    with pytest.raises(ReplayActivityVersionError, match="does not match"):
        RecordedActivityResolver(_RecordedStore(record), _registry(v2)).resolve(
            expected_v2,
            _record_ref(record),
        )


def test_recorded_resolver_rejects_invalid_store_response_without_live_fallback() -> (
    None
):
    record = _record()
    resolver = RecordedActivityResolver(_RecordedStore(object()), _registry())

    with pytest.raises(ReplayActivityCorruptionError, match="invalid data"):
        resolver.resolve(record.activity, _record_ref(record))


@pytest.mark.parametrize("kind", tuple(ReplayActivityKind))
def test_activity_recorder_persists_input_pending_and_success_for_every_kind(
    kind: ReplayActivityKind,
) -> None:
    store = _ActivityWriteStore()

    handle = _accept_recording(store, kind)

    assert store.calls == ["put_payload:input", "accept_record"]
    assert handle.activity.activity_kind is kind
    assert handle.outcome.status is ReplayActivityStatus.PENDING
    assert (
        handle.activity.input_ref
        == store.payloads[
            (handle.activity.activity_id, ReplayActivityPayloadRole.INPUT)
        ].payload_ref
    )
    assert not handle.is_terminal

    completed = handle.succeed(
        {"answer": kind.value},
        completed_at=COMPLETED_AT,
    )

    assert store.calls == [
        "put_payload:input",
        "accept_record",
        "put_payload:output",
        "complete_record",
    ]
    assert completed.record.outcome.status is ReplayActivityStatus.SUCCEEDED
    assert (
        completed.record.outcome.output_ref
        == store.payloads[
            (handle.activity.activity_id, ReplayActivityPayloadRole.OUTPUT)
        ].payload_ref
    )
    assert completed.record.outcome.output_checksum == checksum_for(
        {"answer": kind.value}
    )
    assert completed.record.outcome.output_ref.uri != completed.recorded_ref.uri
    assert handle.is_terminal


def test_activity_recorder_keeps_pending_state_without_executing_live_work() -> None:
    store = _ActivityWriteStore()
    recorder = ActivityRecorder(store)

    handle = _accept_recording(store)

    assert handle.outcome.status is ReplayActivityStatus.PENDING
    assert store.records[handle.activity.activity_id].record.outcome.status is (
        ReplayActivityStatus.PENDING
    )
    assert tuple(store.payloads) == (
        (handle.activity.activity_id, ReplayActivityPayloadRole.INPUT),
    )
    assert not hasattr(recorder, "provider")
    assert not hasattr(recorder, "live_provider")
    assert not hasattr(handle, "provider")
    assert not hasattr(handle, "live_provider")


def test_activity_recorder_records_failed_outcome_with_separate_error_reference() -> (
    None
):
    store = _ActivityWriteStore()
    handle = _accept_recording(store, ReplayActivityKind.HTTP)

    completed = handle.fail(
        "provider_timeout",
        {"reason": "redacted"},
        completed_at=COMPLETED_AT,
    )

    outcome = completed.record.outcome
    assert outcome.status is ReplayActivityStatus.FAILED
    assert outcome.error_class == "provider_timeout"
    assert (
        outcome.error_ref
        == store.payloads[
            (handle.activity.activity_id, ReplayActivityPayloadRole.ERROR)
        ].payload_ref
    )
    assert outcome.error_ref.uri != completed.recorded_ref.uri
    assert outcome.output_ref is None
    assert store.calls[-2:] == ["put_payload:error", "complete_record"]

    assert (
        handle.fail(
            "provider_timeout",
            {"reason": "redacted"},
            completed_at=COMPLETED_AT + timedelta(seconds=10),
        )
        == completed
    )
    with pytest.raises(ReplayActivityRecordingConflictError, match="conflicting error"):
        handle.fail(
            "different_error",
            {"reason": "redacted"},
            completed_at=COMPLETED_AT,
        )
    with pytest.raises(ReplayActivityRecordingConflictError, match="as succeeded"):
        handle.succeed({"answer": "late"}, completed_at=COMPLETED_AT)


def test_activity_recorder_exact_retries_return_the_committed_record() -> None:
    store = _ActivityWriteStore()
    first = _accept_recording(store)
    duplicate = _accept_recording(store)

    assert duplicate.recorded_ref == first.recorded_ref
    assert duplicate.outcome.status is ReplayActivityStatus.PENDING

    committed = first.succeed({"answer": "recorded"}, completed_at=COMPLETED_AT)
    retried = duplicate.succeed(
        {"answer": "recorded"},
        completed_at=COMPLETED_AT,
    )

    assert retried == committed
    resumed = _accept_recording(store)
    assert resumed.is_terminal
    calls_before_terminal_retry = tuple(store.calls)
    assert (
        resumed.succeed(
            {"answer": "recorded"},
            completed_at=COMPLETED_AT + timedelta(seconds=20),
        )
        == committed
    )
    assert tuple(store.calls) == calls_before_terminal_retry
    with pytest.raises(
        ReplayActivityRecordingConflictError, match="conflicting output"
    ):
        resumed.succeed({"answer": "changed"}, completed_at=COMPLETED_AT)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"input_value": {"prompt": "changed"}}, "payload identity collision"),
        ({"contract_version": "newsroom.activity/v2"}, "payload identity collision"),
        ({"tenant_id": "tenant-b"}, "payload identity collision"),
        (
            {"security_classification": SecurityClassification.RESTRICTED},
            "payload identity collision",
        ),
    ],
)
def test_activity_recorder_rejects_conflicting_idempotent_accepts(
    overrides: dict[str, Any],
    message: str,
) -> None:
    store = _ActivityWriteStore()
    _accept_recording(store)

    with pytest.raises(ReplayActivityRecordingConflictError, match=message):
        _accept_recording(store, **overrides)

    assert len(store.records) == 1
    assert (
        store.records["recording-1"].record.outcome.status
        is ReplayActivityStatus.PENDING
    )


@pytest.mark.parametrize(
    ("conflict", "expected_error"),
    [
        ("identity", ReplayActivityMismatchError),
        ("version", ReplayActivityVersionError),
        ("tenant", ReplayActivityTenantMismatchError),
        ("classification", ReplayActivityTenantMismatchError),
        ("checksum", ReplayActivityCorruptionError),
    ],
)
def test_activity_recorder_validates_store_returned_record_binding(
    conflict: str,
    expected_error: type[Exception],
) -> None:
    store = _ActivityWriteStore()

    def transform(write: RecordedActivityWrite) -> RecordedActivityWrite:
        if conflict == "checksum":
            corrupted = _activity_write(write.record)
            object.__setattr__(
                corrupted,
                "recorded_ref",
                replace(
                    corrupted.recorded_ref,
                    expected_checksum=checksum_for("corrupted-record"),
                ),
            )
            return corrupted
        activity = write.record.activity
        if conflict == "identity":
            activity = replace(activity, activity_id="different-activity")
        elif conflict == "version":
            activity = replace(activity, handler_version="handler/other")
        elif conflict == "tenant":
            activity = replace(activity, tenant_id="tenant-b")
        else:
            activity = replace(
                activity,
                security_classification=SecurityClassification.RESTRICTED,
            )
        outcome = replace(write.record.outcome, activity_id=activity.activity_id)
        return _activity_write(ReplayActivityRecord(activity, outcome))

    store.accept_transform = transform

    with pytest.raises(expected_error):
        _accept_recording(store)


@pytest.mark.parametrize("conflict", ["identity", "version", "tenant", "checksum"])
def test_activity_recorder_validates_store_returned_payload_binding(
    conflict: str,
) -> None:
    store = _ActivityWriteStore()

    def transform(write: RecordedActivityPayloadWrite) -> RecordedActivityPayloadWrite:
        if conflict == "checksum":
            corrupted = _payload_write(write.payload)
            object.__setattr__(
                corrupted,
                "payload_ref",
                replace(
                    corrupted.payload_ref,
                    expected_checksum=checksum_for("corrupted-payload"),
                ),
            )
            return corrupted
        if conflict == "identity":
            payload = replace(write.payload, activity_id="different-activity")
        elif conflict == "version":
            payload = replace(write.payload, handler_version="handler/other")
        else:
            payload = replace(write.payload, tenant_id="tenant-b")
        return _payload_write(payload)

    store.payload_transform = transform

    expected_error = (
        ReplayActivityCorruptionError
        if conflict == "checksum"
        else ReplayActivityTenantMismatchError
        if conflict == "tenant"
        else ReplayActivityVersionError
        if conflict == "version"
        else ReplayActivityRecordingConflictError
    )
    with pytest.raises(expected_error):
        _accept_recording(store)
    assert store.calls == ["put_payload:input"]


def test_activity_recorder_rejects_conflicting_completion_and_remains_pending() -> None:
    store = _ActivityWriteStore()
    handle = _accept_recording(store)

    def transform(write: RecordedActivityWrite) -> RecordedActivityWrite:
        different_ref = _ref("different-output", {"answer": "different"})
        different_outcome = replace(
            write.record.outcome,
            output_ref=different_ref,
            output_checksum=different_ref.expected_checksum,
        )
        return _activity_write(
            ReplayActivityRecord(write.record.activity, different_outcome)
        )

    store.complete_transform = transform

    with pytest.raises(ReplayActivityRecordingConflictError, match="completion"):
        handle.succeed({"answer": "recorded"}, completed_at=COMPLETED_AT)
    assert handle.outcome.status is ReplayActivityStatus.PENDING

    store.complete_transform = None
    completed = handle.succeed({"answer": "recorded"}, completed_at=COMPLETED_AT)
    assert completed.record.outcome.status is ReplayActivityStatus.SUCCEEDED


@pytest.mark.parametrize(
    "failure_point",
    [
        "put_payload:input",
        "accept_record",
        "put_payload:output",
        "complete_record",
    ],
)
def test_activity_recorder_does_not_swallow_store_exceptions(
    failure_point: str,
) -> None:
    store = _ActivityWriteStore()
    failure = RuntimeError(f"failure at {failure_point}")

    if failure_point in {"put_payload:input", "accept_record"}:
        store.errors[failure_point] = failure
        with pytest.raises(RuntimeError) as captured:
            _accept_recording(store)
        assert captured.value is failure
        return

    handle = _accept_recording(store)
    store.errors[failure_point] = failure
    with pytest.raises(RuntimeError) as captured:
        handle.succeed({"answer": "recorded"}, completed_at=COMPLETED_AT)
    assert captured.value is failure
    assert handle.outcome.status is ReplayActivityStatus.PENDING


def test_activity_recorder_validates_lifecycle_before_any_durable_write() -> None:
    store = _ActivityWriteStore()

    with pytest.raises(ValueError, match="started_at cannot precede accepted_at"):
        _accept_recording(
            store,
            started_at=ACCEPTED_AT - timedelta(seconds=1),
        )

    assert store.calls == []

    with pytest.raises(TypeError, match="context must be an object"):
        _accept_recording(store, context=["not", "an", "object"])
    assert store.calls == []

    handle = _accept_recording(store)
    calls_before_completion = tuple(store.calls)
    with pytest.raises(ValueError, match="completed_at cannot precede started_at"):
        handle.succeed(
            {"answer": "too early"},
            completed_at=STARTED_AT - timedelta(seconds=1),
        )
    assert tuple(store.calls) == calls_before_completion
    assert handle.outcome.status is ReplayActivityStatus.PENDING
