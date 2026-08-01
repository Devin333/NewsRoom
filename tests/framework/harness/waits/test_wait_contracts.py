from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from framework.events.canonical import checksum_for
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.waits import (
    HARNESS_WAIT_RECORD_SCHEMA,
    HarnessEarlySignalRetentionPolicy,
    HarnessSignalInboxEntry,
    HarnessWaitApprovalEvidenceRecord,
    HarnessWaitCancellationRecord,
    HarnessWaitCauseKind,
    HarnessWaitRegistrationRecord,
    HarnessWaitResumeRecord,
    HarnessWaitScope,
    HarnessWaitSignal,
    HarnessWaitSignalMatch,
    HarnessWaitTimeoutRecord,
    HarnessWaitTimerWakeRecord,
    validate_signal_authorization,
    validate_signal_for_registration,
)


def _ref(value: object) -> str:
    return checksum_for(value)


def _scope(**updates: str) -> HarnessWaitScope:
    values = {
        "wait_id": "wait-for-source",
        "run_id": "run-1",
        "node_instance_id": "node-instance-1",
        "tenant_scope_ref": _ref({"tenant_id": "tenant-1"}),
        "identity_scope_ref": _ref({"subject": "operator-1"}),
        "signal_schema_ref": "source-ready@1",
        "correlation_ref": _ref({"paper_id": "paper-1"}),
    }
    values.update(updates)
    return HarnessWaitScope(**values)


def test_wait_scope_is_immutable_and_canonical() -> None:
    scope = _scope()

    assert HarnessWaitScope.from_dict(scope.to_dict()) == scope
    assert scope.scope_ref == checksum_for(scope.to_dict())
    with pytest.raises(FrozenInstanceError):
        scope.run_id = "changed"  # type: ignore[misc]


def test_all_wait_records_round_trip_with_versioned_schema() -> None:
    scope = _scope()
    registration = HarnessWaitRegistrationRecord(
        scope=scope,
        kind="signal",
        registered_sequence=10,
    )
    signal = HarnessWaitSignal(
        signal_id="signal-1",
        scope=scope,
        payload_ref=_ref({"ready": True}),
        received_sequence=9,
    )
    match = HarnessWaitSignalMatch(
        scope=scope,
        registration_ref=registration.registration_ref,
        signal_ref=signal.signal_ref,
        matched_sequence=11,
    )
    inbox_entry = HarnessSignalInboxEntry(
        signal=signal,
        status="matched",
        match=match,
    )
    timer = HarnessWaitTimerWakeRecord(
        scope=scope,
        deadline_ref=_ref({"deadline": "2026-08-01T00:00:00Z"}),
        timer_event_ref=_ref({"event": "timer-woke"}),
        recorded_sequence=12,
    )
    approval = HarnessWaitApprovalEvidenceRecord(
        scope=scope,
        approval_event_ref=_ref({"event": "approved"}),
        actor_identity_scope_ref=_ref({"actor": "reviewer-1"}),
        approved=True,
        recorded_sequence=13,
    )
    resume = HarnessWaitResumeRecord(
        scope=scope,
        cause_kind=HarnessWaitCauseKind.SIGNAL,
        cause_ref=match.match_ref,
        resumed_sequence=14,
    )
    timeout = HarnessWaitTimeoutRecord(
        scope=scope,
        deadline_ref=_ref({"deadline": "2026-08-01T00:00:00Z"}),
        timeout_event_ref=_ref({"event": "timed-out"}),
        timed_out_sequence=15,
    )
    cancellation = HarnessWaitCancellationRecord(
        scope=scope,
        cancellation_event_ref=_ref({"event": "cancelled"}),
        actor_identity_scope_ref=_ref({"actor": "operator-1"}),
        reason_code="operator_cancelled",
        cancelled_sequence=16,
    )

    record_pairs = (
        (HarnessWaitRegistrationRecord, registration),
        (HarnessWaitSignal, signal),
        (HarnessWaitSignalMatch, match),
        (HarnessSignalInboxEntry, inbox_entry),
        (HarnessWaitTimerWakeRecord, timer),
        (HarnessWaitApprovalEvidenceRecord, approval),
        (HarnessWaitResumeRecord, resume),
        (HarnessWaitTimeoutRecord, timeout),
        (HarnessWaitCancellationRecord, cancellation),
    )
    for record_type, record in record_pairs:
        payload = record.to_dict()
        assert payload["record_schema"] == HARNESS_WAIT_RECORD_SCHEMA
        assert record_type.from_dict(payload) == record

    policy = HarnessEarlySignalRetentionPolicy(
        max_signals=20,
        max_signals_per_scope=4,
        sequence_window=500,
    )
    assert HarnessEarlySignalRetentionPolicy.from_dict(policy.to_dict()) == policy


def test_signal_logical_identity_is_stable_across_delivery_retries() -> None:
    first = HarnessWaitSignal(
        signal_id="signal-1",
        scope=_scope(),
        payload_ref=_ref({"ready": True}),
        received_sequence=7,
    )
    retry = HarnessWaitSignal(
        signal_id="signal-1",
        scope=_scope(),
        payload_ref=first.payload_ref,
        received_sequence=99,
    )

    assert retry.identity_ref == first.identity_ref
    assert retry.signal_ref == first.signal_ref
    assert retry.idempotency_projection() == first.idempotency_projection()


@pytest.mark.parametrize(
    ("field_name", "error_code"),
    (
        ("run_id", "wait_signal_run_scope_mismatch"),
        ("node_instance_id", "wait_signal_node_scope_mismatch"),
        ("tenant_scope_ref", "wait_signal_tenant_scope_mismatch"),
        ("identity_scope_ref", "wait_signal_identity_scope_mismatch"),
        ("signal_schema_ref", "wait_signal_schema_mismatch"),
        ("correlation_ref", "wait_signal_correlation_mismatch"),
    ),
)
def test_signal_registration_matching_requires_every_exact_scope_field(
    field_name: str,
    error_code: str,
) -> None:
    registration = HarnessWaitRegistrationRecord(
        scope=_scope(),
        kind="signal",
        registered_sequence=1,
    )
    replacements = {
        "run_id": "other-run",
        "node_instance_id": "other-node",
        "tenant_scope_ref": _ref({"tenant_id": "other"}),
        "identity_scope_ref": _ref({"subject": "other"}),
        "signal_schema_ref": "other-signal@1",
        "correlation_ref": _ref({"paper_id": "other"}),
    }
    signal = HarnessWaitSignal(
        signal_id="signal-1",
        scope=_scope(**{field_name: replacements[field_name]}),
        payload_ref=_ref({"ready": True}),
        received_sequence=2,
    )

    with pytest.raises(HarnessValidationError) as exc_info:
        validate_signal_for_registration(registration, signal)

    assert exc_info.value.code == error_code


def test_signal_authorization_rejects_self_asserted_tenant_and_identity() -> None:
    signal = HarnessWaitSignal(
        signal_id="signal-1",
        scope=_scope(),
        payload_ref=_ref({"ready": True}),
        received_sequence=2,
    )

    with pytest.raises(HarnessValidationError) as exc_info:
        validate_signal_authorization(
            signal,
            _scope(tenant_scope_ref=_ref({"tenant_id": "other"})),
        )

    assert exc_info.value.code == "wait_signal_authorization_tenant_scope_mismatch"


def test_timer_registration_requires_durable_deadline_reference() -> None:
    with pytest.raises(HarnessValidationError) as exc_info:
        HarnessWaitRegistrationRecord(
            scope=_scope(),
            kind="timer",
            registered_sequence=1,
        )

    assert exc_info.value.code == "timer_deadline_missing"


def test_wait_record_reader_rejects_unknown_schema() -> None:
    registration = HarnessWaitRegistrationRecord(
        scope=_scope(),
        kind="signal",
        registered_sequence=1,
    )
    payload = registration.to_dict()
    payload["record_schema"] = "newsroom.harness.wait-record/v999"

    with pytest.raises(HarnessValidationError) as exc_info:
        HarnessWaitRegistrationRecord.from_dict(payload)

    assert exc_info.value.code == "unsupported_wait_record_schema"
