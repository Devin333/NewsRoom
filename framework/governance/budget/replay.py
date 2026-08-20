from __future__ import annotations

from collections.abc import Iterable

from framework.governance.budget.errors import BudgetHistoryError
from framework.governance.budget.ledger import BudgetLedger
from framework.governance.budget.models import (
    BudgetEvent,
    BudgetReservationStatus,
    BudgetSettlementOutcome,
    BudgetSnapshot,
)
from framework.shared.graph_identity import GraphExecutionIdentity, GraphRunIdentity


def replay_budget_events(
    snapshot: BudgetSnapshot,
    events: Iterable[BudgetEvent],
    *,
    expected_identity: GraphRunIdentity | GraphExecutionIdentity | None = None,
) -> BudgetLedger:
    ledger = BudgetLedger.restore(snapshot)
    seen: set[str] = set()
    expected_revision = snapshot.ledger_revision + 1
    for event in events:
        if not isinstance(event, BudgetEvent):
            raise BudgetHistoryError("replay accepts BudgetEvent values only")
        if event.event_id in seen:
            raise BudgetHistoryError(f"duplicate budget event id: {event.event_id}")
        seen.add(event.event_id)
        if event.ledger_revision != expected_revision:
            raise BudgetHistoryError(
                f"budget event revision gap: expected {expected_revision}, "
                f"received {event.ledger_revision}"
            )
        if event.run_id != ledger.root_scope.run_id:
            raise BudgetHistoryError("budget event crossed run scope")
        if (
            expected_identity is not None
            and event.scope.execution_identity != expected_identity
        ):
            raise BudgetHistoryError(
                "budget event Graph identity does not match the expected replay identity"
            )
        try:
            if ledger.view(event.scope).policy.digest != event.policy_digest:
                raise BudgetHistoryError("budget event policy digest mismatch")
            if event.event_type == "budget_reservation_created":
                if event.reservation is None:
                    raise BudgetHistoryError("created event lacks reservation")
                result = ledger.reserve(
                    event.scope,
                    event.amounts,
                    event.operation_id,
                    event.reservation.idempotency_key,
                    created_at_epoch_ms=event.reservation.created_at_epoch_ms,
                )
                if result != event.reservation:
                    raise BudgetHistoryError("replayed reservation projection changed")
            elif event.event_type == "budget_reservation_denied":
                result = ledger.reserve(
                    event.scope,
                    event.amounts,
                    event.operation_id,
                    event.idempotency_key,
                )
                if getattr(result, "allowed", True):
                    raise BudgetHistoryError("replayed denial became allowed")
                if tuple(getattr(result, "violations", ())) != event.reason_codes:
                    raise BudgetHistoryError("replayed denial reasons changed")
            elif event.event_type == "budget_reservation_settled":
                if event.settlement is None:
                    raise BudgetHistoryError("settled event lacks settlement")
                if ledger.settle(event.reservation_id or "", event.settlement) != event.settlement:
                    raise BudgetHistoryError("replayed settlement projection changed")
            elif event.event_type == "budget_reservation_released":
                if event.settlement is None:
                    raise BudgetHistoryError("released event lacks settlement")
                result = ledger.release(
                    event.reservation_id or "",
                    operation_id=event.operation_id,
                    reason=event.settlement.reason_code or "released",
                    event_id=event.event_id,
                )
                if result != event.settlement:
                    raise BudgetHistoryError("replayed release projection changed")
            elif event.event_type == "budget_reservation_indeterminate":
                result = ledger.mark_indeterminate(
                    event.reservation_id or "",
                    operation_id=event.operation_id,
                    reason=(event.reason_codes[0] if event.reason_codes else "indeterminate"),
                    settled_event_id=event.event_id,
                )
                if result != event.settlement:
                    raise BudgetHistoryError("replayed indeterminate projection changed")
            elif event.event_type == "budget_reservation_expired":
                reservation = ledger.reservation(event.reservation_id or "")
                policy = ledger.view(reservation.scope).policy
                result = ledger.expire(
                    event.reservation_id or "",
                    now_epoch_ms=(
                        reservation.created_at_epoch_ms
                        + policy.reservation_ttl_seconds * 1000
                    ),
                )
                if result != event.settlement:
                    raise BudgetHistoryError("replayed expiry projection changed")
            else:
                raise BudgetHistoryError(f"unknown budget event type: {event.event_type}")
        except BudgetHistoryError:
            raise
        except Exception as exc:
            raise BudgetHistoryError(
                f"budget event replay failed at {event.event_id}: {exc}"
            ) from exc
        if ledger.ledger_revision != event.ledger_revision:
            raise BudgetHistoryError("replayed ledger revision changed")
        if ledger.snapshot().last_event_id != event.event_id:
            raise BudgetHistoryError("replayed event identity changed")
        expected_revision += 1
    return ledger


__all__ = ["replay_budget_events"]
