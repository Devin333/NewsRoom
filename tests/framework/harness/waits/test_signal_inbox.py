from __future__ import annotations

import pytest

from framework.events.canonical import checksum_for
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.waits import (
    HarnessEarlySignalRetentionPolicy,
    HarnessSignalInboxEntryStatus,
    HarnessSignalInboxPort,
    HarnessWaitRegistrationRecord,
    HarnessWaitScope,
    HarnessWaitSignal,
    InMemoryHarnessSignalInbox,
)


def _ref(value: object) -> str:
    return checksum_for(value)


def _scope(**updates: str) -> HarnessWaitScope:
    values = {
        "wait_id": "wait-1",
        "run_id": "run-1",
        "node_instance_id": "node-1",
        "tenant_scope_ref": _ref({"tenant": "tenant-1"}),
        "identity_scope_ref": _ref({"identity": "identity-1"}),
        "signal_schema_ref": "source-ready@1",
        "correlation_ref": _ref({"correlation": "paper-1"}),
    }
    values.update(updates)
    return HarnessWaitScope(**values)


def _signal(
    signal_id: str,
    sequence: int,
    *,
    scope: HarnessWaitScope | None = None,
    payload: object | None = None,
) -> HarnessWaitSignal:
    return HarnessWaitSignal(
        signal_id=signal_id,
        scope=scope or _scope(),
        payload_ref=_ref({"payload": signal_id} if payload is None else payload),
        received_sequence=sequence,
    )


def test_in_memory_inbox_implements_signal_port() -> None:
    assert isinstance(InMemoryHarnessSignalInbox(), HarnessSignalInboxPort)


def test_early_signal_is_matched_once_after_registration() -> None:
    inbox = InMemoryHarnessSignalInbox()
    scope = _scope()
    entry = inbox.put_signal(_signal("signal-1", 3), authorized_scope=scope)
    registration = HarnessWaitRegistrationRecord(
        scope=scope,
        kind="signal",
        registered_sequence=4,
    )

    first = inbox.consume_matching(registration, matched_sequence=5)
    repeated = inbox.consume_matching(registration, matched_sequence=99)

    assert first is not None
    assert repeated == first
    assert first.signal_ref == entry.signal.signal_ref
    assert inbox.pending_count == 0
    assert (
        inbox.list_entries(authorized_scope=scope)[0].status
        is HarnessSignalInboxEntryStatus.MATCHED
    )


def test_matching_uses_stable_receipt_order_not_insertion_order() -> None:
    inbox = InMemoryHarnessSignalInbox()
    scope = _scope()
    later = inbox.put_signal(_signal("later", 8), authorized_scope=scope)
    earlier = inbox.put_signal(_signal("earlier", 6), authorized_scope=scope)
    registration = HarnessWaitRegistrationRecord(
        scope=scope,
        kind="signal",
        registered_sequence=9,
    )

    match = inbox.consume_matching(registration, matched_sequence=10)

    assert match is not None
    assert match.signal_ref == earlier.signal.signal_ref
    assert match.signal_ref != later.signal.signal_ref


def test_identical_duplicate_is_idempotent_even_with_later_delivery_sequence() -> None:
    inbox = InMemoryHarnessSignalInbox()
    scope = _scope()
    first = _signal("signal-1", 3)
    retry = HarnessWaitSignal(
        signal_id=first.signal_id,
        scope=first.scope,
        payload_ref=first.payload_ref,
        received_sequence=7,
    )

    first_entry = inbox.put_signal(first, authorized_scope=scope)
    retry_entry = inbox.put_signal(retry, authorized_scope=scope)

    assert retry_entry == first_entry
    assert retry_entry.signal.received_sequence == 3
    assert inbox.entry_count == 1


def test_duplicate_signal_identity_with_conflicting_payload_is_rejected() -> None:
    inbox = InMemoryHarnessSignalInbox()
    scope = _scope()
    inbox.put_signal(_signal("signal-1", 3), authorized_scope=scope)

    with pytest.raises(HarnessValidationError) as exc_info:
        inbox.put_signal(
            _signal("signal-1", 4, payload={"conflict": True}),
            authorized_scope=scope,
        )

    assert exc_info.value.code == "wait_signal_identity_conflict"
    assert inbox.entry_count == 1


@pytest.mark.parametrize(
    ("authorized_scope", "error_code"),
    (
        (
            _scope(tenant_scope_ref=_ref({"tenant": "other"})),
            "wait_signal_authorization_tenant_scope_mismatch",
        ),
        (
            _scope(identity_scope_ref=_ref({"identity": "other"})),
            "wait_signal_authorization_identity_scope_mismatch",
        ),
    ),
)
def test_inbox_rejects_wrong_authorized_scope_without_mutation(
    authorized_scope: HarnessWaitScope,
    error_code: str,
) -> None:
    inbox = InMemoryHarnessSignalInbox()

    with pytest.raises(HarnessValidationError) as exc_info:
        inbox.put_signal(_signal("signal-1", 3), authorized_scope=authorized_scope)

    assert exc_info.value.code == error_code
    assert inbox.entry_count == 0


def test_wrong_correlation_does_not_resume_another_wait() -> None:
    inbox = InMemoryHarnessSignalInbox()
    wrong_scope = _scope(correlation_ref=_ref({"correlation": "other"}))
    inbox.put_signal(
        _signal("wrong", 3, scope=wrong_scope),
        authorized_scope=wrong_scope,
    )
    registration = HarnessWaitRegistrationRecord(
        scope=_scope(),
        kind="signal",
        registered_sequence=4,
    )

    assert inbox.consume_matching(registration, matched_sequence=5) is None
    assert inbox.pending_count == 1


def test_per_scope_retention_bound_fails_closed_without_evicting() -> None:
    inbox = InMemoryHarnessSignalInbox(
        HarnessEarlySignalRetentionPolicy(
            max_signals=4,
            max_signals_per_scope=2,
            sequence_window=100,
        )
    )
    scope = _scope()
    inbox.put_signal(_signal("signal-1", 1), authorized_scope=scope)
    inbox.put_signal(_signal("signal-2", 2), authorized_scope=scope)

    with pytest.raises(HarnessValidationError) as exc_info:
        inbox.put_signal(_signal("signal-3", 3), authorized_scope=scope)

    assert exc_info.value.code == "early_signal_scope_retention_exhausted"
    assert inbox.entry_count == 2


def test_sequence_window_prunes_deterministically_without_wall_clock() -> None:
    inbox = InMemoryHarnessSignalInbox(
        HarnessEarlySignalRetentionPolicy(
            max_signals=3,
            max_signals_per_scope=3,
            sequence_window=3,
        )
    )
    scope = _scope()
    first = inbox.put_signal(_signal("signal-1", 1), authorized_scope=scope)
    inbox.put_signal(_signal("signal-2", 2), authorized_scope=scope)

    expired = inbox.prune_early_signals(through_sequence=4)

    assert expired == (first.signal.signal_ref,)
    assert [
        entry.signal.signal_id for entry in inbox.list_entries(authorized_scope=scope)
    ] == ["signal-2"]


def test_signal_outside_retention_window_is_rejected() -> None:
    inbox = InMemoryHarnessSignalInbox(
        HarnessEarlySignalRetentionPolicy(
            max_signals=3,
            max_signals_per_scope=3,
            sequence_window=3,
        )
    )
    scope = _scope()
    inbox.prune_early_signals(through_sequence=10)

    with pytest.raises(HarnessValidationError) as exc_info:
        inbox.put_signal(_signal("stale", 7), authorized_scope=scope)

    assert exc_info.value.code == "early_signal_retention_expired"
    assert inbox.entry_count == 0
