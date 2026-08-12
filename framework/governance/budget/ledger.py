from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from threading import RLock
from time import time
from typing import Callable, Iterable

from framework.governance.budget.errors import (
    BudgetContractError,
    BudgetEventWriteError,
    BudgetHistoryError,
    BudgetIdentityConflictError,
    BudgetStateError,
)
from framework.governance.budget.events import BudgetEventSink
from framework.governance.budget.models import (
    BUDGET_SCHEMA_VERSION,
    BudgetAmounts,
    BudgetDecision,
    BudgetEvent,
    BudgetLimits,
    BudgetOperationRecord,
    BudgetPolicy,
    BudgetReasonCode,
    BudgetReservation,
    BudgetReservationStatus,
    BudgetScopeRef,
    BudgetScopeSnapshot,
    BudgetScopeType,
    BudgetSettlement,
    BudgetSettlementOutcome,
    BudgetSnapshot,
    BudgetUsage,
    BudgetView,
    operation_fingerprint,
)
from framework.shared.json import stable_json_dumps


class BudgetLedger:
    """Process-local canonical cumulative LLM budget state machine."""

    def __init__(
        self,
        root_scope: BudgetScopeRef,
        root_policy: BudgetPolicy,
        *,
        event_sink: BudgetEventSink | None = None,
        clock_epoch_ms: Callable[[], int] | None = None,
    ) -> None:
        if root_scope.scope_type is not BudgetScopeType.RUN:
            raise BudgetContractError("root scope must have type run")
        if root_scope.policy_revision != root_policy.policy_revision:
            raise BudgetContractError("root scope policy revision does not match policy")
        self._lock = RLock()
        self._root_scope_id = root_scope.scope_id
        self._scopes: dict[str, BudgetScopeRef] = {root_scope.scope_id: root_scope}
        self._policies: dict[str, BudgetPolicy] = {root_scope.scope_id: root_policy}
        self._committed: dict[str, BudgetAmounts] = {
            root_scope.scope_id: BudgetAmounts()
        }
        self._baseline_committed: dict[str, BudgetAmounts] = {
            root_scope.scope_id: BudgetAmounts()
        }
        self._reserved: dict[str, BudgetAmounts] = {
            root_scope.scope_id: BudgetAmounts()
        }
        self._reservations: dict[str, BudgetReservation] = {}
        self._operations: dict[str, BudgetOperationRecord] = {}
        self._idempotency_index: dict[str, str] = {}
        self._revision = 0
        self._last_event_id: str | None = None
        self._event_sink = event_sink
        self._clock_epoch_ms = clock_epoch_ms or (lambda: int(time() * 1000))

    @property
    def root_scope(self) -> BudgetScopeRef:
        with self._lock:
            return self._scopes[self._root_scope_id]

    @property
    def ledger_revision(self) -> int:
        with self._lock:
            return self._revision

    def register_scope(
        self,
        scope: BudgetScopeRef,
        policy: BudgetPolicy,
    ) -> BudgetView:
        with self._lock:
            existing = self._scopes.get(scope.scope_id)
            if existing is not None:
                if existing != scope or self._policies[scope.scope_id] != policy:
                    raise BudgetIdentityConflictError(
                        f"scope identity already registered: {scope.scope_id}"
                    )
                return self._view_locked(scope.scope_id)
            if scope.run_id != self.root_scope.run_id:
                raise BudgetContractError("child scope must use the root run_id")
            if scope.scope_type is BudgetScopeType.RUN:
                raise BudgetContractError("only one run root scope is allowed")
            if scope.parent_scope_id not in self._scopes:
                raise BudgetContractError("child scope parent is not registered")
            if scope.policy_revision != policy.policy_revision:
                raise BudgetContractError("scope policy revision does not match policy")
            self._scopes[scope.scope_id] = scope
            self._policies[scope.scope_id] = policy
            self._committed[scope.scope_id] = BudgetAmounts()
            self._baseline_committed[scope.scope_id] = BudgetAmounts()
            self._reserved[scope.scope_id] = BudgetAmounts()
            return self._view_locked(scope.scope_id)

    def preflight(
        self,
        scope: BudgetScopeRef,
        request: BudgetAmounts,
        policy: BudgetPolicy | None = None,
    ) -> BudgetDecision:
        with self._lock:
            self._require_scope(scope, policy)
            violations, projected = self._projected_for_request(scope.scope_id, request)
            return BudgetDecision(
                allowed=not violations,
                violations=violations,
                projected_usage=projected,
                reservation_id=None,
                ledger_revision=self._revision,
            )

    def reserve(
        self,
        scope: BudgetScopeRef,
        request: BudgetAmounts,
        operation_id: str,
        idempotency_key: str,
        *,
        policy: BudgetPolicy | None = None,
        created_at_epoch_ms: int | None = None,
    ) -> BudgetReservation | BudgetDecision:
        with self._lock:
            scope_policy = self._require_scope(scope, policy)
            operation_id = _required_identity(operation_id, "operation_id")
            idempotency_key = _required_identity(idempotency_key, "idempotency_key")
            fingerprint = operation_fingerprint(
                scope=scope,
                requested=request,
                policy_digest=scope_policy.digest,
            )
            existing = self._existing_operation(
                operation_id=operation_id,
                idempotency_key=idempotency_key,
                fingerprint=fingerprint,
            )
            if existing is not None:
                if existing.reservation_id is not None:
                    if existing.reservation is None:
                        raise BudgetHistoryError(
                            "operation record lacks its reservation projection"
                        )
                    return existing.reservation
                if existing.decision is not None:
                    return existing.decision
                raise BudgetHistoryError("operation record has no reservation or decision")

            violations, projected = self._projected_for_request(scope.scope_id, request)
            if violations:
                new_revision = self._revision + 1
                event_id = self._event_id("denied", operation_id, new_revision)
                decision = BudgetDecision(
                    allowed=False,
                    violations=violations,
                    projected_usage=replace(
                        projected,
                        ledger_revision=new_revision,
                    ),
                    reservation_id=None,
                    ledger_revision=new_revision,
                )
                event = BudgetEvent(
                    event_id=event_id,
                    event_type="budget_reservation_denied",
                    run_id=scope.run_id,
                    scope=scope,
                    policy_digest=scope_policy.digest,
                    ledger_revision=new_revision,
                    operation_id=operation_id,
                    idempotency_key=idempotency_key,
                    reservation_id=None,
                    amounts=request,
                    reason_codes=violations,
                    outcome="denied",
                )
                self._append_event(event)
                self._operations[operation_id] = BudgetOperationRecord(
                    operation_id=operation_id,
                    idempotency_key=idempotency_key,
                    fingerprint=fingerprint,
                    reservation_id=None,
                    decision=decision,
                )
                self._idempotency_index[idempotency_key] = operation_id
                self._revision = new_revision
                self._last_event_id = event_id
                return decision

            new_revision = self._revision + 1
            reservation_id = self._reservation_id(operation_id, idempotency_key)
            event_id = self._event_id("created", reservation_id, new_revision)
            created_at = (
                self._clock_epoch_ms()
                if created_at_epoch_ms is None
                else created_at_epoch_ms
            )
            reservation = BudgetReservation(
                reservation_id=reservation_id,
                operation_id=operation_id,
                idempotency_key=idempotency_key,
                scope=scope,
                policy_digest=scope_policy.digest,
                requested=request,
                status=BudgetReservationStatus.RESERVED,
                created_event_id=event_id,
                created_at_epoch_ms=created_at,
            )
            event = BudgetEvent(
                event_id=event_id,
                event_type="budget_reservation_created",
                run_id=scope.run_id,
                scope=scope,
                policy_digest=scope_policy.digest,
                ledger_revision=new_revision,
                operation_id=operation_id,
                idempotency_key=idempotency_key,
                reservation_id=reservation_id,
                amounts=request,
                outcome="reserved",
                reservation=reservation,
            )
            self._append_event(event)
            self._apply_reserved_delta(scope.scope_id, request, add=True)
            self._reservations[reservation_id] = reservation
            self._operations[operation_id] = BudgetOperationRecord(
                operation_id=operation_id,
                idempotency_key=idempotency_key,
                fingerprint=fingerprint,
                reservation_id=reservation_id,
                reservation=reservation,
            )
            self._idempotency_index[idempotency_key] = operation_id
            self._revision = new_revision
            self._last_event_id = event_id
            return reservation

    def settle(
        self,
        reservation_id: str,
        settlement: BudgetSettlement,
    ) -> BudgetSettlement:
        with self._lock:
            reservation = self._reservation_or_recorded(reservation_id)
            record = self._operations[reservation.operation_id]
            reconciling = False
            if record.settlement is not None:
                if record.settlement.command_projection() == settlement.command_projection():
                    return record.settlement
                reconciling = (
                    record.settlement.outcome
                    is BudgetSettlementOutcome.INDETERMINATE
                    and settlement.outcome
                    is not BudgetSettlementOutcome.INDETERMINATE
                )
                if not reconciling:
                    raise BudgetIdentityConflictError("conflicting duplicate settlement")
            self._validate_settlement(reservation, settlement)
            allowed_statuses = {BudgetReservationStatus.RESERVED}
            if reconciling:
                allowed_statuses.add(BudgetReservationStatus.INDETERMINATE)
            if reservation.status not in allowed_statuses:
                raise BudgetStateError(
                    f"reservation is not open: {reservation.status.value}"
                )
            if settlement.outcome is BudgetSettlementOutcome.INDETERMINATE:
                return self.mark_indeterminate(
                    reservation_id,
                    operation_id=settlement.operation_id,
                    reason=settlement.reason_code or BudgetReasonCode.DISPATCH_INDETERMINATE.value,
                    settled_event_id=settlement.settled_event_id,
                )
            if not self._settlement_fits_reservation(reservation, settlement.actual):
                return self.mark_indeterminate(
                    reservation_id,
                    operation_id=settlement.operation_id,
                    reason=BudgetReasonCode.ACTUAL_EXCEEDS_RESERVATION.value,
                    settled_event_id=settlement.settled_event_id,
                )

            new_revision = self._revision + 1
            event = BudgetEvent(
                event_id=settlement.settled_event_id,
                event_type="budget_reservation_settled",
                run_id=reservation.scope.run_id,
                scope=reservation.scope,
                policy_digest=reservation.policy_digest,
                ledger_revision=new_revision,
                operation_id=reservation.operation_id,
                idempotency_key=reservation.idempotency_key,
                reservation_id=reservation.reservation_id,
                amounts=settlement.actual,
                reason_codes=(
                    (settlement.reason_code,)
                    if settlement.reason_code is not None
                    else ()
                ),
                outcome=settlement.outcome.value,
                settlement=settlement,
            )
            self._append_event(event)
            self._apply_reserved_delta(
                reservation.scope.scope_id, reservation.requested, add=False
            )
            self._apply_committed_delta(
                reservation.scope.scope_id, settlement.actual, add=True
            )
            self._reservations[reservation_id] = replace(
                reservation, status=BudgetReservationStatus.SETTLED
            )
            terminal_reservation = replace(
                reservation, status=BudgetReservationStatus.SETTLED
            )
            self._operations[reservation.operation_id] = replace(
                record,
                reservation=terminal_reservation,
                settlement=settlement,
            )
            self._revision = new_revision
            self._last_event_id = settlement.settled_event_id
            return settlement

    def _settlement_fits_reservation(
        self,
        reservation: BudgetReservation,
        actual: BudgetAmounts,
    ) -> bool:
        requested = reservation.requested
        if actual.llm_calls > requested.llm_calls:
            return False
        ancestor_limits = tuple(
            self._policies[scope_id].limits
            for scope_id in self._ancestors(reservation.scope.scope_id)
        )
        if (
            any(limits.input_tokens is not None for limits in ancestor_limits)
            and actual.input_tokens > requested.input_tokens
        ):
            return False
        if (
            any(limits.cached_input_tokens is not None for limits in ancestor_limits)
            and actual.cached_input_tokens > requested.cached_input_tokens
        ):
            return False
        generation_is_dimension_bounded = any(
            limits.output_tokens is not None or limits.reasoning_tokens is not None
            for limits in ancestor_limits
        )
        if generation_is_dimension_bounded and (
            actual.output_tokens > requested.output_tokens
            or actual.reasoning_tokens > requested.reasoning_tokens
        ):
            return False
        if (
            any(limits.total_tokens is not None for limits in ancestor_limits)
            and actual.total_tokens > requested.total_tokens
        ):
            return False

        cost_is_bounded = any(
            limits.estimated_cost_usd is not None for limits in ancestor_limits
        )
        if cost_is_bounded and (
            actual.estimated_cost_usd > requested.estimated_cost_usd
        ):
            return False

        for scope_id in self._ancestors(reservation.scope.scope_id):
            projected = (
                self._committed[scope_id]
                .add(self._reserved[scope_id])
                .subtract(requested)
                .add(actual)
            )
            if self._policies[scope_id].limits.violations(projected):
                return False
        return True

    def release(
        self,
        reservation_id: str,
        *,
        operation_id: str,
        reason: str,
        request_dispatched: bool = False,
        event_id: str | None = None,
    ) -> BudgetSettlement:
        with self._lock:
            return self._release_locked(
                reservation_id,
                operation_id=operation_id,
                reason=reason,
                request_dispatched=request_dispatched,
                event_id=event_id,
                event_type="budget_reservation_released",
                status=BudgetReservationStatus.RELEASED,
            )

    def expire(
        self,
        reservation_id: str,
        *,
        now_epoch_ms: int | None = None,
    ) -> BudgetSettlement:
        with self._lock:
            reservation = self._reservation(reservation_id)
            policy = self._policies[reservation.scope.scope_id]
            now = self._clock_epoch_ms() if now_epoch_ms is None else now_epoch_ms
            if isinstance(now, bool) or not isinstance(now, int) or now < 0:
                raise BudgetContractError("now_epoch_ms must be a non-negative integer")
            expires_at = reservation.created_at_epoch_ms + policy.reservation_ttl_seconds * 1000
            if now < expires_at:
                raise BudgetStateError("reservation has not expired")
            return self._release_locked(
                reservation_id,
                operation_id=reservation.operation_id,
                reason=BudgetReasonCode.RESERVATION_EXPIRED.value,
                request_dispatched=False,
                event_id=self._event_id("expired", reservation_id, self._revision + 1),
                event_type="budget_reservation_expired",
                status=BudgetReservationStatus.EXPIRED,
            )

    def mark_indeterminate(
        self,
        reservation_id: str,
        *,
        operation_id: str,
        reason: str,
        settled_event_id: str | None = None,
    ) -> BudgetSettlement:
        with self._lock:
            reservation = self._reservation_or_recorded(reservation_id)
            record = self._operations[reservation.operation_id]
            if operation_id != reservation.operation_id:
                raise BudgetIdentityConflictError(
                    "indeterminate operation identity mismatch"
                )
            reason = _required_identity(reason, "reason")
            if record.settlement is not None:
                if (
                    record.settlement.outcome
                    is BudgetSettlementOutcome.INDETERMINATE
                    and record.settlement.reason_code == reason
                    and (
                        settled_event_id is None
                        or settled_event_id == record.settlement.settled_event_id
                    )
                ):
                    return record.settlement
                raise BudgetIdentityConflictError(
                    "conflicting duplicate indeterminate settlement"
                )
            if reservation.status is not BudgetReservationStatus.RESERVED:
                raise BudgetStateError("only an open reservation can become indeterminate")
            new_revision = self._revision + 1
            event_id = settled_event_id or self._event_id(
                "indeterminate", reservation_id, new_revision
            )
            settlement = BudgetSettlement(
                reservation_id=reservation_id,
                operation_id=operation_id,
                scope=reservation.scope,
                policy_digest=reservation.policy_digest,
                actual=BudgetAmounts(),
                request_dispatched=True,
                cache_hit=False,
                outcome=BudgetSettlementOutcome.INDETERMINATE,
                settled_event_id=event_id,
                reason_code=reason,
            )
            event = BudgetEvent(
                event_id=event_id,
                event_type="budget_reservation_indeterminate",
                run_id=reservation.scope.run_id,
                scope=reservation.scope,
                policy_digest=reservation.policy_digest,
                ledger_revision=new_revision,
                operation_id=operation_id,
                idempotency_key=reservation.idempotency_key,
                reservation_id=reservation_id,
                amounts=reservation.requested,
                reason_codes=(reason,),
                outcome=BudgetReservationStatus.INDETERMINATE.value,
                settlement=settlement,
            )
            self._append_event(event)
            self._reservations[reservation_id] = replace(
                reservation, status=BudgetReservationStatus.INDETERMINATE
            )
            terminal_reservation = replace(
                reservation, status=BudgetReservationStatus.INDETERMINATE
            )
            self._operations[operation_id] = replace(
                record,
                reservation=terminal_reservation,
                settlement=settlement,
            )
            self._revision = new_revision
            self._last_event_id = event_id
            return settlement

    def view(self, scope: BudgetScopeRef | str) -> BudgetView:
        with self._lock:
            scope_id = scope.scope_id if isinstance(scope, BudgetScopeRef) else scope
            return self._view_locked(scope_id)

    def available_total_tokens(self, scope: BudgetScopeRef | str) -> int | None:
        """Return the tightest finite total-token allowance across the scope tree."""

        with self._lock:
            scope_id = scope.scope_id if isinstance(scope, BudgetScopeRef) else scope
            if scope_id not in self._scopes:
                raise BudgetContractError(f"unknown budget scope: {scope_id}")
            available: list[int] = []
            for ancestor_id in self._ancestors(scope_id):
                limit = self._policies[ancestor_id].limits.total_tokens
                if limit is None:
                    continue
                used = self._committed[ancestor_id].add(
                    self._reserved[ancestor_id]
                )
                available.append(max(0, limit - used.total_tokens))
            return min(available) if available else None

    def reservation(self, reservation_id: str) -> BudgetReservation:
        with self._lock:
            return self._reservation(reservation_id)

    def snapshot(self, scope: BudgetScopeRef | str | None = None) -> BudgetSnapshot:
        with self._lock:
            if scope is not None:
                scope_id = scope.scope_id if isinstance(scope, BudgetScopeRef) else scope
                if scope_id not in self._scopes:
                    raise BudgetContractError(f"unknown budget scope: {scope_id}")
                if scope_id != self._root_scope_id:
                    raise BudgetContractError(
                        "authoritative snapshots are only available for the root scope"
                    )
            root_policy = self._policies[self._root_scope_id]
            return BudgetSnapshot(
                root_scope_id=self._root_scope_id,
                policy_digest=root_policy.digest,
                scopes=tuple(
                    BudgetScopeSnapshot(
                        scope=self._scopes[scope_id],
                        policy=self._policies[scope_id],
                        committed=self._committed[scope_id],
                        reserved=self._reserved[scope_id],
                        baseline_committed=self._baseline_committed[scope_id],
                    )
                    for scope_id in sorted(self._scopes)
                ),
                open_reservations=tuple(
                    self._reservations[key]
                    for key in sorted(self._reservations)
                    if self._reservations[key].status
                    in {
                        BudgetReservationStatus.RESERVED,
                        BudgetReservationStatus.INDETERMINATE,
                    }
                ),
                operation_records=tuple(
                    self._operations[key] for key in sorted(self._operations)
                ),
                last_event_id=self._last_event_id,
                ledger_revision=self._revision,
            )

    @classmethod
    def restore(
        cls,
        snapshot: BudgetSnapshot,
        *,
        event_sink: BudgetEventSink | None = None,
        clock_epoch_ms: Callable[[], int] | None = None,
    ) -> "BudgetLedger":
        if not isinstance(snapshot, BudgetSnapshot):
            raise BudgetHistoryError("restore requires BudgetSnapshot")
        _reject_duplicate_identities(
            (item.scope.scope_id for item in snapshot.scopes),
            "scope",
        )
        _reject_duplicate_identities(
            (item.reservation_id for item in snapshot.open_reservations),
            "open reservation",
        )
        _reject_duplicate_identities(
            (item.operation_id for item in snapshot.operation_records),
            "operation",
        )
        _reject_duplicate_identities(
            (item.idempotency_key for item in snapshot.operation_records),
            "idempotency",
        )
        scopes = {item.scope.scope_id: item for item in snapshot.scopes}
        root = scopes.get(snapshot.root_scope_id)
        if root is None or root.scope.scope_type is not BudgetScopeType.RUN:
            raise BudgetHistoryError("snapshot root scope is missing or invalid")
        if root.policy.digest != snapshot.policy_digest:
            raise BudgetHistoryError("snapshot policy digest mismatch")
        ledger = cls(
            root.scope,
            root.policy,
            event_sink=event_sink,
            clock_epoch_ms=clock_epoch_ms,
        )
        pending = [item for key, item in scopes.items() if key != snapshot.root_scope_id]
        while pending:
            progressed = False
            for item in tuple(pending):
                if item.scope.parent_scope_id in ledger._scopes:
                    ledger.register_scope(item.scope, item.policy)
                    pending.remove(item)
                    progressed = True
            if not progressed:
                raise BudgetHistoryError("snapshot scope graph is cyclic or incomplete")
        ledger._committed = {key: item.committed for key, item in scopes.items()}
        ledger._baseline_committed = {
            key: item.baseline_committed for key, item in scopes.items()
        }
        ledger._reserved = {key: item.reserved for key, item in scopes.items()}
        ledger._reservations = {
            item.reservation_id: item for item in snapshot.open_reservations
        }
        ledger._operations = {
            item.operation_id: item for item in snapshot.operation_records
        }
        for item in snapshot.operation_records:
            if item.reservation is not None:
                ledger._reservations.setdefault(
                    item.reservation.reservation_id,
                    item.reservation,
                )
        ledger._idempotency_index = {
            item.idempotency_key: item.operation_id
            for item in snapshot.operation_records
        }
        ledger._revision = snapshot.ledger_revision
        ledger._last_event_id = snapshot.last_event_id
        try:
            ledger._validate_committed_totals(snapshot)
            ledger._validate_restored_state()
        except (BudgetContractError, BudgetStateError) as exc:
            raise BudgetHistoryError(str(exc)) from exc
        return ledger

    def _validate_committed_totals(self, snapshot: BudgetSnapshot) -> None:
        baselines = {
            item.scope.scope_id: (
                item.baseline_committed
                if item.baseline_committed is not None
                else item.committed
            )
            for item in snapshot.scopes
        }
        legacy_scope_ids = {
            item.scope.scope_id
            for item in snapshot.scopes
            if item.baseline_committed is None
        }
        if legacy_scope_ids:
            # Older v1 snapshots did not carry an explicit imported baseline.
            # Infer it once from their terminal records, then validate all totals.
            for record in snapshot.operation_records:
                if record.settlement is None:
                    continue
                settlement = record.settlement
                for ancestor_id in self._ancestors(settlement.scope.scope_id):
                    if ancestor_id in legacy_scope_ids:
                        baselines[ancestor_id] = baselines[ancestor_id].subtract(
                            settlement.actual
                        )
        expected = dict(baselines)
        for record in snapshot.operation_records:
            if record.settlement is None:
                continue
            settlement = record.settlement
            scope_id = settlement.scope.scope_id
            if scope_id not in expected:
                raise BudgetStateError("settlement references unknown scope")
            for ancestor_id in self._ancestors(scope_id):
                expected[ancestor_id] = expected[ancestor_id].add(settlement.actual)
        for scope_id, committed in self._committed.items():
            if committed != expected[scope_id]:
                raise BudgetStateError(
                    f"snapshot committed totals do not match operation history for {scope_id}"
                )
        self._baseline_committed = baselines

    def _require_scope(
        self, scope: BudgetScopeRef, policy: BudgetPolicy | None
    ) -> BudgetPolicy:
        registered = self._scopes.get(scope.scope_id)
        if registered != scope:
            raise BudgetContractError("budget scope is not registered or does not match")
        registered_policy = self._policies[scope.scope_id]
        if policy is not None and policy != registered_policy:
            raise BudgetContractError("budget policy does not match registered scope")
        return registered_policy

    def _existing_operation(
        self,
        *,
        operation_id: str,
        idempotency_key: str,
        fingerprint: str,
    ) -> BudgetOperationRecord | None:
        by_operation = self._operations.get(operation_id)
        indexed_operation = self._idempotency_index.get(idempotency_key)
        if indexed_operation is not None and indexed_operation != operation_id:
            raise BudgetIdentityConflictError("idempotency key already belongs to another operation")
        if by_operation is None:
            return None
        if (
            by_operation.idempotency_key != idempotency_key
            or by_operation.fingerprint != fingerprint
        ):
            raise BudgetIdentityConflictError("operation identity reused with different content")
        return by_operation

    def _projected_for_request(
        self, scope_id: str, request: BudgetAmounts
    ) -> tuple[tuple[str, ...], BudgetUsage]:
        violations: set[str] = set()
        for ancestor_id in self._ancestors(scope_id):
            used = self._committed[ancestor_id].add(self._reserved[ancestor_id])
            projected = used.add(request)
            violations.update(self._policies[ancestor_id].limits.violations(projected))
        local_committed = self._committed[scope_id]
        local_reserved = self._reserved[scope_id]
        projected_reserved = local_reserved.add(request)
        projected_total = local_committed.add(projected_reserved)
        usage = BudgetUsage(
            committed=local_committed,
            reserved=projected_reserved,
            available=self._effective_available(scope_id, extra=request),
            ledger_revision=self._revision,
        )
        return tuple(sorted(violations)), usage

    def _view_locked(self, scope_id: str) -> BudgetView:
        if scope_id not in self._scopes:
            raise BudgetContractError(f"unknown budget scope: {scope_id}")
        policy = self._policies[scope_id]
        committed = self._committed[scope_id]
        reserved = self._reserved[scope_id]
        return BudgetView(
            scope=self._scopes[scope_id],
            policy=policy,
            usage=BudgetUsage(
                committed=committed,
                reserved=reserved,
                available=self._effective_available(scope_id),
                ledger_revision=self._revision,
            ),
        )

    def _effective_available(
        self,
        scope_id: str,
        *,
        extra: BudgetAmounts | None = None,
    ) -> BudgetAmounts:
        amount_fields = (
            "llm_calls",
            "input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "cached_input_tokens",
            "estimated_cost_usd",
        )
        availabilities: list[BudgetAmounts] = []
        for ancestor_id in self._ancestors(scope_id):
            used = self._committed[ancestor_id].add(self._reserved[ancestor_id])
            if extra is not None:
                used = used.add(extra)
            availabilities.append(
                self._policies[ancestor_id].limits.available(used)
            )
        return BudgetAmounts(
            **{
                field_name: min(
                    getattr(available, field_name)
                    for available in availabilities
                )
                for field_name in amount_fields
            }
        )

    def _ancestors(self, scope_id: str) -> Iterable[str]:
        current: str | None = scope_id
        seen: set[str] = set()
        while current is not None:
            if current in seen or current not in self._scopes:
                raise BudgetContractError("invalid budget scope graph")
            seen.add(current)
            yield current
            current = self._scopes[current].parent_scope_id

    def _apply_reserved_delta(
        self, scope_id: str, amount: BudgetAmounts, *, add: bool
    ) -> None:
        for ancestor_id in self._ancestors(scope_id):
            current = self._reserved[ancestor_id]
            self._reserved[ancestor_id] = (
                current.add(amount) if add else current.subtract(amount)
            )

    def _apply_committed_delta(
        self, scope_id: str, amount: BudgetAmounts, *, add: bool
    ) -> None:
        for ancestor_id in self._ancestors(scope_id):
            current = self._committed[ancestor_id]
            self._committed[ancestor_id] = (
                current.add(amount) if add else current.subtract(amount)
            )

    def _reservation(self, reservation_id: str) -> BudgetReservation:
        reservation_id = _required_identity(reservation_id, "reservation_id")
        try:
            return self._reservations[reservation_id]
        except KeyError as exc:
            raise BudgetStateError(f"unknown reservation: {reservation_id}") from exc

    def _reservation_or_recorded(self, reservation_id: str) -> BudgetReservation:
        reservation_id = _required_identity(reservation_id, "reservation_id")
        reservation = self._reservations.get(reservation_id)
        if reservation is not None:
            return reservation
        for record in self._operations.values():
            if record.reservation_id == reservation_id and record.reservation is not None:
                return record.reservation
        raise BudgetStateError(f"unknown reservation: {reservation_id}")

    def _release_locked(
        self,
        reservation_id: str,
        *,
        operation_id: str,
        reason: str,
        request_dispatched: bool,
        event_id: str | None,
        event_type: str,
        status: BudgetReservationStatus,
    ) -> BudgetSettlement:
        reservation = self._reservation_or_recorded(reservation_id)
        record = self._operations[reservation.operation_id]
        if operation_id != reservation.operation_id:
            raise BudgetIdentityConflictError("release operation identity mismatch")
        if request_dispatched:
            raise BudgetStateError("dispatched reservation cannot be released")
        reason = _required_identity(reason, "reason")
        if record.settlement is not None:
            if (
                record.settlement.outcome is BudgetSettlementOutcome.CANCELLED
                and record.settlement.reason_code == reason
                and (
                    event_id is None
                    or event_id == record.settlement.settled_event_id
                )
            ):
                return record.settlement
            raise BudgetIdentityConflictError("conflicting duplicate release")
        if reservation.status is not BudgetReservationStatus.RESERVED:
            raise BudgetStateError("only an open reservation can be released")
        new_revision = self._revision + 1
        terminal_event_id = event_id or self._event_id(
            status.value, reservation_id, new_revision
        )
        settlement = BudgetSettlement(
            reservation_id=reservation_id,
            operation_id=operation_id,
            scope=reservation.scope,
            policy_digest=reservation.policy_digest,
            actual=BudgetAmounts(),
            request_dispatched=False,
            cache_hit=False,
            outcome=BudgetSettlementOutcome.CANCELLED,
            settled_event_id=terminal_event_id,
            reason_code=reason,
        )
        event = BudgetEvent(
            event_id=terminal_event_id,
            event_type=event_type,
            run_id=reservation.scope.run_id,
            scope=reservation.scope,
            policy_digest=reservation.policy_digest,
            ledger_revision=new_revision,
            operation_id=operation_id,
            idempotency_key=reservation.idempotency_key,
            reservation_id=reservation_id,
            amounts=reservation.requested,
            reason_codes=(reason,),
            outcome=status.value,
            settlement=settlement,
        )
        self._append_event(event)
        self._apply_reserved_delta(
            reservation.scope.scope_id, reservation.requested, add=False
        )
        terminal_reservation = replace(reservation, status=status)
        self._reservations[reservation_id] = terminal_reservation
        self._operations[operation_id] = replace(
            record,
            reservation=terminal_reservation,
            settlement=settlement,
        )
        self._revision = new_revision
        self._last_event_id = terminal_event_id
        return settlement

    def _validate_settlement(
        self,
        reservation: BudgetReservation,
        settlement: BudgetSettlement,
    ) -> None:
        if settlement.reservation_id != reservation.reservation_id:
            raise BudgetIdentityConflictError("settlement reservation identity mismatch")
        if settlement.operation_id != reservation.operation_id:
            raise BudgetIdentityConflictError("settlement operation identity mismatch")
        if settlement.scope != reservation.scope:
            raise BudgetIdentityConflictError("settlement scope mismatch")
        if settlement.policy_digest != reservation.policy_digest:
            raise BudgetIdentityConflictError("settlement policy digest mismatch")
        if settlement.cache_hit and settlement.request_dispatched:
            raise BudgetContractError("cache hit cannot claim provider dispatch")

    def _validate_restored_state(self) -> None:
        expected_reserved = {scope_id: BudgetAmounts() for scope_id in self._scopes}
        for reservation in self._reservations.values():
            if reservation.scope.scope_id not in self._scopes:
                raise BudgetStateError("reservation references unknown scope")
            policy = self._policies[reservation.scope.scope_id]
            if reservation.policy_digest != policy.digest:
                raise BudgetStateError("reservation policy digest mismatch")
            if reservation.status not in {
                BudgetReservationStatus.RESERVED,
                BudgetReservationStatus.INDETERMINATE,
            }:
                continue
            for ancestor_id in self._ancestors(reservation.scope.scope_id):
                expected_reserved[ancestor_id] = expected_reserved[ancestor_id].add(
                    reservation.requested
                )
        if expected_reserved != self._reserved:
            raise BudgetStateError("snapshot reserved totals do not match reservations")
        for scope_id, scope in self._scopes.items():
            if scope.run_id != self.root_scope.run_id:
                raise BudgetStateError("snapshot scope crossed run boundary")
            total = self._committed[scope_id].add(self._reserved[scope_id])
            violations = self._policies[scope_id].limits.violations(total)
            if violations:
                raise BudgetStateError(
                    f"snapshot exceeds policy for {scope_id}: {violations}"
                )
        for operation_id, record in self._operations.items():
            if operation_id != record.operation_id:
                raise BudgetStateError("operation map identity mismatch")
            if self._idempotency_index.get(record.idempotency_key) != operation_id:
                raise BudgetStateError("operation idempotency index mismatch")
            if record.reservation_id is not None:
                if record.reservation is None:
                    raise BudgetStateError("operation lacks reservation projection")
                if record.reservation.reservation_id != record.reservation_id:
                    raise BudgetStateError("operation reservation identity mismatch")
                reservation = record.reservation
                if self._reservations.get(record.reservation_id) != reservation:
                    raise BudgetStateError(
                        "operation reservation conflicts with reservation index"
                    )
                if reservation.operation_id != operation_id:
                    raise BudgetStateError("reservation operation identity mismatch")
                if reservation.idempotency_key != record.idempotency_key:
                    raise BudgetStateError("reservation idempotency identity mismatch")
                if reservation.scope.scope_id not in self._scopes:
                    raise BudgetStateError("operation reservation references unknown scope")
                policy = self._policies[reservation.scope.scope_id]
                if reservation.policy_digest != policy.digest:
                    raise BudgetStateError("operation reservation policy mismatch")
                if record.fingerprint != operation_fingerprint(
                    scope=reservation.scope,
                    requested=reservation.requested,
                    policy_digest=reservation.policy_digest,
                ):
                    raise BudgetStateError("operation fingerprint mismatch")
                if record.decision is not None:
                    raise BudgetStateError(
                        "reserved operation cannot also carry a denial decision"
                    )
                if record.settlement is not None:
                    self._validate_settlement(reservation, record.settlement)
                    expected_status = (
                        BudgetReservationStatus.INDETERMINATE
                        if record.settlement.outcome
                        is BudgetSettlementOutcome.INDETERMINATE
                        else (
                            BudgetReservationStatus.EXPIRED
                            if record.settlement.reason_code
                            == BudgetReasonCode.RESERVATION_EXPIRED.value
                            else BudgetReservationStatus.RELEASED
                        )
                        if record.settlement.outcome
                        is BudgetSettlementOutcome.CANCELLED
                        else BudgetReservationStatus.SETTLED
                    )
                    if reservation.status is not expected_status:
                        raise BudgetStateError(
                            "reservation status conflicts with settlement"
                        )
                elif reservation.status is not BudgetReservationStatus.RESERVED:
                    raise BudgetStateError(
                        "non-reserved operation lacks a terminal settlement"
                    )
            else:
                if record.reservation is not None or record.settlement is not None:
                    raise BudgetStateError(
                        "denied operation carries reservation state"
                    )
                if record.decision is None or record.decision.allowed:
                    raise BudgetStateError(
                        "operation without reservation must carry a denial decision"
                    )
                if (
                    record.decision.ledger_revision < 1
                    or record.decision.ledger_revision > self._revision
                    or record.decision.projected_usage.ledger_revision
                    != record.decision.ledger_revision
                ):
                    raise BudgetStateError("denial decision revision exceeds ledger")

    def _append_event(self, event: BudgetEvent) -> None:
        if self._event_sink is None:
            return
        try:
            self._event_sink.append(event)
        except Exception as exc:
            if getattr(self._event_sink, "required", True):
                raise BudgetEventWriteError("required budget event append failed") from exc

    @staticmethod
    def _reservation_id(operation_id: str, idempotency_key: str) -> str:
        digest = sha256(f"{operation_id}\0{idempotency_key}".encode("utf-8")).hexdigest()
        return f"budget-reservation:{digest}"

    @staticmethod
    def _event_id(kind: str, identity: str, revision: int) -> str:
        digest = sha256(f"{kind}\0{identity}\0{revision}".encode("utf-8")).hexdigest()
        return f"budget-event:{digest}"


def restore_legacy_budget_snapshot(
    snapshot: dict[str, object],
    *,
    run_id: str,
    policy: BudgetPolicy,
    scope_id: str | None = None,
    event_sink: BudgetEventSink | None = None,
    clock_epoch_ms: Callable[[], int] | None = None,
) -> BudgetLedger:
    allowed = {"llm_calls", "token_usage", "estimated_cost_usd"}
    unknown = sorted(set(snapshot) - allowed)
    if unknown:
        raise BudgetHistoryError(f"legacy budget snapshot has unknown fields: {unknown}")
    token_usage = snapshot.get("token_usage", {})
    if not isinstance(token_usage, dict):
        raise BudgetHistoryError("legacy token_usage must be an object")
    token_allowed = {
        "input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "cached_input_tokens",
        "total_tokens",
        "estimated_cost_usd",
    }
    token_unknown = sorted(set(token_usage) - token_allowed)
    if token_unknown:
        raise BudgetHistoryError(
            f"legacy token_usage has unknown fields: {token_unknown}"
        )
    root = BudgetScopeRef(
        run_id=run_id,
        scope_id=scope_id or f"run:{run_id}",
        scope_type=BudgetScopeType.RUN,
        policy_revision=policy.policy_revision,
    )
    ledger = BudgetLedger(
        root,
        policy,
        event_sink=event_sink,
        clock_epoch_ms=clock_epoch_ms,
    )
    committed = BudgetAmounts(
        llm_calls=snapshot.get("llm_calls", 0),
        input_tokens=token_usage.get("input_tokens", 0),
        output_tokens=token_usage.get("output_tokens", 0),
        reasoning_tokens=token_usage.get("reasoning_tokens", 0),
        cached_input_tokens=token_usage.get("cached_input_tokens", 0),
        estimated_cost_usd=snapshot.get(
            "estimated_cost_usd", token_usage.get("estimated_cost_usd", "0")
        ),
    )
    if policy.limits.violations(committed):
        raise BudgetHistoryError("legacy snapshot exceeds canonical policy")
    ledger._committed[root.scope_id] = committed
    ledger._baseline_committed[root.scope_id] = committed
    return ledger


def _required_identity(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise BudgetContractError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > 512:
        raise BudgetContractError(f"{field_name} is required and must be bounded")
    return normalized


def _reject_duplicate_identities(values: Iterable[str], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise BudgetHistoryError(f"snapshot contains duplicate {label} identity")
        seen.add(value)


__all__ = ["BudgetLedger", "restore_legacy_budget_snapshot"]
