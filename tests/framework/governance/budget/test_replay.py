from __future__ import annotations

from copy import deepcopy

import pytest

from framework.governance.budget import (
    BudgetAmounts,
    BudgetEvent,
    BudgetHistoryError,
    BudgetLedger,
    BudgetLimits,
    BudgetPolicy,
    BudgetReservation,
    BudgetScopeRef,
    BudgetSettlement,
    BudgetSnapshot,
    InMemoryBudgetEventSink,
    replay_budget_events,
    restore_legacy_budget_snapshot,
)


def _ledger() -> tuple[
    BudgetLedger,
    BudgetScopeRef,
    BudgetPolicy,
    InMemoryBudgetEventSink,
]:
    policy = BudgetPolicy(
        policy_revision="policy-v1",
        limits=BudgetLimits(llm_calls=2, input_tokens=20),
    )
    root = BudgetScopeRef(
        run_id="run-1",
        scope_id="root",
        scope_type="run",
        policy_revision=policy.policy_revision,
    )
    sink = InMemoryBudgetEventSink()
    return BudgetLedger(root, policy, event_sink=sink, clock_epoch_ms=lambda: 1_000), root, policy, sink


def test_snapshot_serialization_restore_is_exact() -> None:
    ledger, root, policy, _ = _ledger()
    first = ledger.reserve(
        root,
        BudgetAmounts(llm_calls=1, input_tokens=10),
        "operation-1",
        "key-1",
    )
    assert isinstance(first, BudgetReservation)
    ledger.settle(
        first.reservation_id,
        BudgetSettlement(
            reservation_id=first.reservation_id,
            operation_id=first.operation_id,
            scope=root,
            policy_digest=policy.digest,
            actual=BudgetAmounts(llm_calls=1, input_tokens=8),
            request_dispatched=True,
            cache_hit=False,
            outcome="succeeded",
            settled_event_id="settlement-1",
        ),
    )
    second = ledger.reserve(
        root,
        BudgetAmounts(llm_calls=1, input_tokens=10),
        "operation-2",
        "key-2",
    )
    assert isinstance(second, BudgetReservation)

    encoded = ledger.snapshot().to_dict()
    restored = BudgetLedger.restore(BudgetSnapshot.from_dict(encoded))

    assert restored.snapshot().to_dict() == encoded
    assert (
        restored.reserve(
            root,
            BudgetAmounts(llm_calls=1, input_tokens=10),
            "operation-2",
            "key-2",
        )
        == second
    )


def test_older_v1_snapshot_without_baseline_is_normalized_on_next_write() -> None:
    ledger, root, policy, _ = _ledger()
    reservation = ledger.reserve(
        root,
        BudgetAmounts(llm_calls=1, input_tokens=10),
        "operation-1",
        "key-1",
    )
    assert isinstance(reservation, BudgetReservation)
    ledger.settle(
        reservation.reservation_id,
        BudgetSettlement(
            reservation_id=reservation.reservation_id,
            operation_id=reservation.operation_id,
            scope=root,
            policy_digest=policy.digest,
            actual=BudgetAmounts(llm_calls=1, input_tokens=8),
            request_dispatched=True,
            cache_hit=False,
            outcome="succeeded",
            settled_event_id="settlement-1",
        ),
    )
    older_v1 = deepcopy(ledger.snapshot().to_dict())
    for scope in older_v1["scopes"]:
        scope.pop("baseline_committed")

    restored = BudgetLedger.restore(BudgetSnapshot.from_dict(older_v1))
    normalized = restored.snapshot().to_dict()

    assert normalized["scopes"][0]["baseline_committed"] == BudgetAmounts().to_dict()
    assert normalized["scopes"][0]["committed"] == older_v1["scopes"][0]["committed"]


def test_offline_replay_rebuilds_identical_snapshot() -> None:
    ledger, root, policy, sink = _ledger()
    initial = ledger.snapshot()
    reservation = ledger.reserve(
        root,
        BudgetAmounts(llm_calls=1, input_tokens=10),
        "operation-1",
        "key-1",
    )
    assert isinstance(reservation, BudgetReservation)
    ledger.mark_indeterminate(
        reservation.reservation_id,
        operation_id=reservation.operation_id,
        reason="provider_response_lost",
    )
    ledger.settle(
        reservation.reservation_id,
        BudgetSettlement(
            reservation_id=reservation.reservation_id,
            operation_id=reservation.operation_id,
            scope=root,
            policy_digest=policy.digest,
            actual=BudgetAmounts(llm_calls=1, input_tokens=9),
            request_dispatched=True,
            cache_hit=False,
            outcome="succeeded",
            settled_event_id="reconciled-1",
        ),
    )
    denied = ledger.reserve(
        root,
        BudgetAmounts(llm_calls=2, input_tokens=20),
        "operation-2",
        "key-2",
    )
    assert denied.allowed is False

    replayed = replay_budget_events(initial, sink.events())

    assert replayed.snapshot().to_dict() == ledger.snapshot().to_dict()


def test_replay_rejects_revision_gap_and_duplicate_event() -> None:
    ledger, root, _, sink = _ledger()
    initial = ledger.snapshot()
    reservation = ledger.reserve(
        root,
        BudgetAmounts(llm_calls=1),
        "operation-1",
        "key-1",
    )
    assert isinstance(reservation, BudgetReservation)
    event = sink.events()[0]
    broken = BudgetEvent.from_dict(
        {**event.to_dict(), "ledger_revision": event.ledger_revision + 1}
    )

    with pytest.raises(BudgetHistoryError, match="revision gap"):
        replay_budget_events(initial, [broken])
    with pytest.raises(BudgetHistoryError, match="duplicate"):
        replay_budget_events(initial, [event, event])


def test_legacy_snapshot_is_read_only_migrated_to_canonical_schema() -> None:
    policy = BudgetPolicy(
        policy_revision="policy-v1",
        limits=BudgetLimits(llm_calls=10, input_tokens=100),
    )
    legacy = {
        "llm_calls": 2,
        "token_usage": {
            "input_tokens": 20,
            "output_tokens": 5,
            "reasoning_tokens": 1,
            "cached_input_tokens": 3,
            "total_tokens": 26,
        },
        "estimated_cost_usd": 0.25,
    }

    ledger = restore_legacy_budget_snapshot(
        legacy,
        run_id="run-legacy",
        policy=policy,
    )
    payload = ledger.snapshot().to_dict()

    assert payload["schema_version"] == "newsroom.budget/v1"
    assert payload["open_reservations"] == []
    assert "token_usage" not in payload


@pytest.mark.parametrize(
    "tamper",
    ["duplicate_scope", "fingerprint", "policy_digest", "status", "committed"],
)
def test_restore_rejects_tampered_snapshot_identity_or_state(tamper: str) -> None:
    ledger, root, _, _ = _ledger()
    reservation = ledger.reserve(
        root,
        BudgetAmounts(llm_calls=1, input_tokens=10),
        "operation-1",
        "key-1",
    )
    assert isinstance(reservation, BudgetReservation)
    payload = deepcopy(ledger.snapshot().to_dict())
    if tamper == "duplicate_scope":
        payload["scopes"].append(deepcopy(payload["scopes"][0]))
    elif tamper == "fingerprint":
        payload["operation_records"][0]["fingerprint"] = "sha256:" + "0" * 64
    elif tamper == "policy_digest":
        payload["open_reservations"][0]["policy_digest"] = "sha256:" + "1" * 64
    elif tamper == "committed":
        payload["scopes"][0]["committed"]["input_tokens"] = 1
    else:
        payload["open_reservations"][0]["status"] = "settled"

    with pytest.raises(BudgetHistoryError):
        BudgetLedger.restore(BudgetSnapshot.from_dict(payload))
