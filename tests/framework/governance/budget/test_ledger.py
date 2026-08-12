from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from framework.governance.budget import (
    BudgetAmounts,
    BudgetDecision,
    BudgetEventWriteError,
    BudgetIdentityConflictError,
    BudgetLedger,
    BudgetLimits,
    BudgetPolicy,
    BudgetReservation,
    BudgetReservationStatus,
    BudgetScopeRef,
    BudgetSettlement,
    BudgetSettlementOutcome,
    BudgetStateError,
    InMemoryBudgetEventSink,
)


def _root(
    *,
    limits: BudgetLimits | None = None,
    event_sink: object | None = None,
) -> tuple[BudgetLedger, BudgetScopeRef, BudgetPolicy]:
    policy = BudgetPolicy(
        policy_revision="policy-v1",
        limits=limits or BudgetLimits(llm_calls=3, input_tokens=100),
    )
    scope = BudgetScopeRef(
        run_id="run-1",
        scope_id="run:run-1",
        scope_type="run",
        policy_revision=policy.policy_revision,
    )
    return (
        BudgetLedger(scope, policy, event_sink=event_sink, clock_epoch_ms=lambda: 1_000),
        scope,
        policy,
    )


def _request(*, calls: int = 1, input_tokens: int = 10) -> BudgetAmounts:
    return BudgetAmounts(llm_calls=calls, input_tokens=input_tokens)


def _settlement(
    reservation: BudgetReservation,
    policy: BudgetPolicy,
    *,
    input_tokens: int = 8,
    event_id: str = "settlement-1",
    outcome: str = "succeeded",
) -> BudgetSettlement:
    return BudgetSettlement(
        reservation_id=reservation.reservation_id,
        operation_id=reservation.operation_id,
        scope=reservation.scope,
        policy_digest=policy.digest,
        actual=BudgetAmounts(llm_calls=1, input_tokens=input_tokens),
        request_dispatched=True,
        cache_hit=False,
        outcome=outcome,
        settled_event_id=event_id,
    )


def test_reserve_and_settle_are_exactly_once() -> None:
    ledger, scope, policy = _root()
    request = _request()

    first = ledger.reserve(scope, request, "operation-1", "key-1")
    repeated = ledger.reserve(scope, request, "operation-1", "key-1")

    assert isinstance(first, BudgetReservation)
    assert repeated == first
    assert ledger.view(scope).usage.reserved == request
    assert ledger.ledger_revision == 1

    settlement = _settlement(first, policy)
    assert ledger.settle(first.reservation_id, settlement) == settlement
    revision = ledger.ledger_revision
    assert ledger.settle(first.reservation_id, settlement) == settlement

    usage = ledger.view(scope).usage
    assert usage.committed == settlement.actual
    assert usage.reserved == BudgetAmounts()
    assert ledger.ledger_revision == revision == 2


def test_conflicting_reserve_and_settlement_fail_without_mutation() -> None:
    ledger, scope, policy = _root()
    reservation = ledger.reserve(scope, _request(), "operation-1", "key-1")
    assert isinstance(reservation, BudgetReservation)
    before = ledger.snapshot().to_dict()

    with pytest.raises(BudgetIdentityConflictError):
        ledger.reserve(scope, _request(input_tokens=11), "operation-1", "key-1")
    assert ledger.snapshot().to_dict() == before

    settled = _settlement(reservation, policy)
    ledger.settle(reservation.reservation_id, settled)
    after = ledger.snapshot().to_dict()
    with pytest.raises(BudgetIdentityConflictError):
        ledger.settle(
            reservation.reservation_id,
            _settlement(reservation, policy, input_tokens=7, event_id="settlement-2"),
        )
    assert ledger.snapshot().to_dict() == after


def test_child_scope_is_constrained_by_root_and_has_read_only_view() -> None:
    ledger, root, _ = _root(limits=BudgetLimits(llm_calls=1, input_tokens=10))
    child_policy = BudgetPolicy(
        policy_revision="child-v1",
        limits=BudgetLimits(llm_calls=10, input_tokens=1_000),
    )
    child = BudgetScopeRef(
        run_id=root.run_id,
        scope_id="agent:one",
        scope_type="agent_loop",
        parent_scope_id=root.scope_id,
        policy_revision=child_policy.policy_revision,
    )
    ledger.register_scope(child, child_policy)

    reservation = ledger.reserve(child, _request(), "operation-1", "key-1")
    denied = ledger.reserve(child, _request(), "operation-2", "key-2")

    assert isinstance(reservation, BudgetReservation)
    assert isinstance(denied, BudgetDecision)
    assert denied.allowed is False
    assert denied.violations == ("max_input_tokens", "max_llm_calls")
    assert ledger.view(child).usage.available.llm_calls == 0
    assert ledger.view(root).usage.reserved == _request()
    with pytest.raises(FrozenInstanceError):
        ledger.view(child).usage.committed.llm_calls = 99  # type: ignore[misc]


def test_derived_total_token_limit_is_atomic_without_becoming_a_dimension() -> None:
    ledger, scope, _ = _root(
        limits=BudgetLimits(total_tokens=10),
    )

    first = ledger.reserve(
        scope,
        BudgetAmounts(input_tokens=4, output_tokens=3, reasoning_tokens=3),
        "operation-1",
        "key-1",
    )
    denied = ledger.reserve(
        scope,
        BudgetAmounts(input_tokens=1),
        "operation-2",
        "key-2",
    )

    assert isinstance(first, BudgetReservation)
    assert isinstance(denied, BudgetDecision)
    assert denied.violations == ("max_total_tokens",)
    assert "total_tokens" not in BudgetAmounts().to_dict()


def test_release_requires_proven_no_dispatch() -> None:
    ledger, scope, _ = _root()
    reservation = ledger.reserve(scope, _request(), "operation-1", "key-1")
    assert isinstance(reservation, BudgetReservation)

    with pytest.raises(BudgetStateError, match="dispatched"):
        ledger.release(
            reservation.reservation_id,
            operation_id=reservation.operation_id,
            reason="transport_failed",
            request_dispatched=True,
        )

    released = ledger.release(
        reservation.reservation_id,
        operation_id=reservation.operation_id,
        reason="transport_failed_before_dispatch",
    )
    assert released.outcome is BudgetSettlementOutcome.CANCELLED
    assert ledger.view(scope).usage.reserved == BudgetAmounts()


def test_unknown_dispatch_and_overage_remain_indeterminate_until_reconciled() -> None:
    ledger, scope, policy = _root()
    reservation = ledger.reserve(scope, _request(), "operation-1", "key-1")
    assert isinstance(reservation, BudgetReservation)

    indeterminate = ledger.mark_indeterminate(
        reservation.reservation_id,
        operation_id=reservation.operation_id,
        reason="provider_response_lost",
    )
    assert indeterminate.outcome is BudgetSettlementOutcome.INDETERMINATE
    assert ledger.view(scope).usage.reserved == reservation.requested
    assert (
        ledger.reservation(reservation.reservation_id).status
        is BudgetReservationStatus.INDETERMINATE
    )

    actual = _settlement(
        reservation,
        policy,
        input_tokens=9,
        event_id="reconciled-settlement",
    )
    assert ledger.settle(reservation.reservation_id, actual) == actual
    assert ledger.view(scope).usage.committed == actual.actual
    assert ledger.view(scope).usage.reserved == BudgetAmounts()

    second = ledger.reserve(scope, _request(), "operation-2", "key-2")
    assert isinstance(second, BudgetReservation)
    overage = ledger.settle(
        second.reservation_id,
        _settlement(second, policy, input_tokens=11, event_id="overage"),
    )
    assert overage.outcome is BudgetSettlementOutcome.INDETERMINATE
    assert overage.reason_code == "actual_exceeds_reservation"
    assert ledger.view(scope).usage.reserved == second.requested


def test_failed_settlement_projects_stable_reason_code_to_event() -> None:
    sink = InMemoryBudgetEventSink()
    ledger, scope, policy = _root(event_sink=sink)
    reservation = ledger.reserve(scope, _request(), "operation-1", "key-1")
    assert isinstance(reservation, BudgetReservation)
    ledger.settle(
        reservation.reservation_id,
        BudgetSettlement(
            reservation_id=reservation.reservation_id,
            operation_id=reservation.operation_id,
            scope=scope,
            policy_digest=policy.digest,
            actual=BudgetAmounts(llm_calls=1),
            request_dispatched=True,
            cache_hit=False,
            outcome="failed",
            settled_event_id="failed-settlement",
            reason_code="provider_auth_failed",
        ),
    )

    event = sink.events()[-1]
    assert event.reason_codes == ("provider_auth_failed",)


def test_required_event_append_failure_rolls_back_admission() -> None:
    class _FailingSink:
        required = True

        def append(self, event: object) -> None:
            raise OSError("durable store unavailable")

    ledger, scope, _ = _root(event_sink=_FailingSink())

    with pytest.raises(BudgetEventWriteError):
        ledger.reserve(scope, _request(), "operation-1", "key-1")

    assert ledger.ledger_revision == 0
    assert ledger.view(scope).usage.committed == BudgetAmounts()
    assert ledger.view(scope).usage.reserved == BudgetAmounts()


@pytest.mark.parametrize("terminal", ["settle", "indeterminate", "release"])
def test_required_event_append_failure_preserves_open_reservation(
    terminal: str,
) -> None:
    class _FlakySink:
        required = True

        def __init__(self) -> None:
            self.fail = False

        def append(self, event: object) -> None:
            if self.fail:
                raise OSError("durable store unavailable")

    sink = _FlakySink()
    ledger, scope, policy = _root(event_sink=sink)
    reservation = ledger.reserve(scope, _request(), "operation-1", "key-1")
    assert isinstance(reservation, BudgetReservation)
    before = ledger.snapshot().to_dict()
    sink.fail = True

    with pytest.raises(BudgetEventWriteError):
        if terminal == "settle":
            ledger.settle(reservation.reservation_id, _settlement(reservation, policy))
        elif terminal == "indeterminate":
            ledger.mark_indeterminate(
                reservation.reservation_id,
                operation_id=reservation.operation_id,
                reason="provider_response_lost",
            )
        else:
            ledger.release(
                reservation.reservation_id,
                operation_id=reservation.operation_id,
                reason="cache_preparation_failed_before_dispatch",
            )

    assert ledger.snapshot().to_dict() == before
    assert ledger.reservation(reservation.reservation_id).status is BudgetReservationStatus.RESERVED
    assert ledger.ledger_revision == 1

    sink.fail = False
    if terminal == "settle":
        result = ledger.settle(reservation.reservation_id, _settlement(reservation, policy))
        assert result.outcome is BudgetSettlementOutcome.SUCCEEDED
    elif terminal == "indeterminate":
        result = ledger.mark_indeterminate(
            reservation.reservation_id,
            operation_id=reservation.operation_id,
            reason="provider_response_lost",
        )
        assert result.outcome is BudgetSettlementOutcome.INDETERMINATE
    else:
        result = ledger.release(
            reservation.reservation_id,
            operation_id=reservation.operation_id,
            reason="cache_preparation_failed_before_dispatch",
        )
        assert result.outcome is BudgetSettlementOutcome.CANCELLED


def test_indeterminate_and_release_duplicate_identity_conflicts_are_atomic() -> None:
    ledger, scope, _ = _root()
    reservation = ledger.reserve(scope, _request(), "operation-1", "key-1")
    assert isinstance(reservation, BudgetReservation)

    first = ledger.mark_indeterminate(
        reservation.reservation_id,
        operation_id=reservation.operation_id,
        reason="provider_response_lost",
        settled_event_id="indeterminate-1",
    )
    before = ledger.snapshot().to_dict()
    assert ledger.mark_indeterminate(
        reservation.reservation_id,
        operation_id=reservation.operation_id,
        reason="provider_response_lost",
        settled_event_id="indeterminate-1",
    ) == first
    with pytest.raises(BudgetIdentityConflictError):
        ledger.mark_indeterminate(
            reservation.reservation_id,
            operation_id=reservation.operation_id,
            reason="provider_response_lost_again",
            settled_event_id="indeterminate-2",
        )
    assert ledger.snapshot().to_dict() == before

    ledger2, scope2, _ = _root()
    reservation2 = ledger2.reserve(scope2, _request(), "operation-1", "key-1")
    assert isinstance(reservation2, BudgetReservation)
    released = ledger2.release(
        reservation2.reservation_id,
        operation_id=reservation2.operation_id,
        reason="before_dispatch",
        event_id="release-1",
    )
    before_release = ledger2.snapshot().to_dict()
    assert ledger2.release(
        reservation2.reservation_id,
        operation_id=reservation2.operation_id,
        reason="before_dispatch",
        event_id="release-1",
    ) == released
    with pytest.raises(BudgetIdentityConflictError):
        ledger2.release(
            reservation2.reservation_id,
            operation_id=reservation2.operation_id,
            reason="different_reason",
            event_id="release-2",
        )
    assert ledger2.snapshot().to_dict() == before_release


def test_events_are_allowlisted_and_do_not_accept_sensitive_metadata() -> None:
    sink = InMemoryBudgetEventSink()
    ledger, scope, policy = _root(event_sink=sink)
    reservation = ledger.reserve(scope, _request(), "operation-1", "key-1")
    assert isinstance(reservation, BudgetReservation)
    ledger.settle(reservation.reservation_id, _settlement(reservation, policy))

    payload = str([event.to_dict() for event in sink.events()])
    assert "raw_prompt" not in payload
    assert "provider_response" not in payload
    assert "tool_payload" not in payload
    assert "secret" not in payload
