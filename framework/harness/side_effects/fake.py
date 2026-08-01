from __future__ import annotations

import math
import threading
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from framework.events.canonical import checksum_for
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.side_effects.models import (
    HarnessSideEffectAttemptLease,
    HarnessSideEffectAttemptStatus,
    HarnessSideEffectDecision,
    HarnessSideEffectDisposition,
    HarnessSideEffectIntent,
    HarnessSideEffectOutcome,
)
from framework.shared.time import utc_now


class InMemoryHarnessSideEffectStore:
    """Counting contract store with exact scope and idempotency enforcement."""

    def __init__(
        self,
        *,
        attempt_lease_seconds: float = 30.0,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        lease_seconds = float(attempt_lease_seconds)
        if not math.isfinite(lease_seconds) or lease_seconds <= 0:
            raise ValueError("attempt_lease_seconds must be a finite positive number")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self.decisions_by_ref: dict[str, HarnessSideEffectDecision] = {}
        self.decisions_by_id: dict[str, HarnessSideEffectDecision] = {}
        self.decisions_by_effect: dict[str, HarnessSideEffectDecision] = {}
        self.decisions_by_idempotency: dict[str, HarnessSideEffectDecision] = {}
        self.outcomes_by_effect: dict[str, HarnessSideEffectOutcome] = {}
        self.outcomes_by_idempotency: dict[str, HarnessSideEffectOutcome] = {}
        self.attempts_by_effect: dict[str, int] = {}
        self.attempt_leases_by_effect: dict[str, HarnessSideEffectAttemptLease] = {}
        self.attempt_leases_by_id: dict[str, HarnessSideEffectAttemptLease] = {}
        self.attempt_leases_by_lease_id: dict[str, HarnessSideEffectAttemptLease] = {}
        self.decision_write_count = 0
        self.outcome_write_count = 0
        self.disposition_write_count = 0
        self.attempt_lease_seconds = lease_seconds
        self._clock = clock
        self._lock = threading.RLock()

    def put_decision(
        self, decision: HarnessSideEffectDecision
    ) -> HarnessSideEffectDecision:
        if not isinstance(decision, HarnessSideEffectDecision):
            raise TypeError("decision must be HarnessSideEffectDecision")
        assert decision.checksum is not None
        with self._lock:
            candidates = (
                self.decisions_by_id.get(decision.decision_id),
                self.decisions_by_ref.get(decision.checksum),
                self.decisions_by_effect.get(decision.effect_id),
                self.decisions_by_idempotency.get(decision.idempotency_key),
            )
            for existing in candidates:
                if existing is None:
                    continue
                if existing != decision:
                    raise HarnessValidationError(
                        "side-effect decision identity is immutable"
                    )
                return existing
            self.decisions_by_id[decision.decision_id] = decision
            self.decisions_by_ref[decision.checksum] = decision
            self.decisions_by_effect[decision.effect_id] = decision
            self.decisions_by_idempotency[decision.idempotency_key] = decision
            self.decision_write_count += 1
            return decision

    def put_outcome(
        self,
        outcome: HarnessSideEffectOutcome,
    ) -> HarnessSideEffectOutcome:
        if not isinstance(outcome, HarnessSideEffectOutcome):
            raise TypeError("outcome must be HarnessSideEffectOutcome")
        with self._lock:
            if (
                outcome.effect_id in self.attempt_leases_by_effect
                or outcome.attempt_id is not None
            ):
                raise _attempt_error(
                    "fenced_side_effect_attempt_required",
                    "fenced side-effect outcome requires complete_attempt",
                    effect_id=outcome.effect_id,
                )
            decision = self.decisions_by_ref.get(outcome.decision_ref)
            if decision is None:
                raise HarnessValidationError(
                    "side-effect outcome has no durable authorization"
                )
            _assert_outcome_matches_decision(outcome, decision)
            return self._persist_outcome(outcome)

    def complete_attempt(
        self,
        attempt: HarnessSideEffectAttemptLease,
        outcome: HarnessSideEffectOutcome,
    ) -> HarnessSideEffectOutcome:
        if not isinstance(outcome, HarnessSideEffectOutcome):
            raise TypeError("outcome must be HarnessSideEffectOutcome")
        with self._lock:
            current = self._assert_current_attempt(attempt)
            decision = self.decisions_by_ref.get(outcome.decision_ref)
            if decision is None:
                raise HarnessValidationError(
                    "side-effect outcome has no durable authorization"
                )
            _assert_outcome_matches_decision(outcome, decision)
            outcome = _bind_outcome_to_attempt(outcome, current)
            existing = self._existing_outcome(outcome)
            if existing is not None:
                return existing
            self._assert_lease_accepts_result(current)
            committed = self._persist_outcome(outcome)
            self._resolve_current_attempt(
                current,
                termination_confirmed=True,
                outcome_ref=committed.checksum,
            )
            return committed

    def reconcile_attempt(
        self,
        attempt: HarnessSideEffectAttemptLease,
        outcome: HarnessSideEffectOutcome,
    ) -> HarnessSideEffectOutcome:
        if not isinstance(outcome, HarnessSideEffectOutcome):
            raise TypeError("outcome must be HarnessSideEffectOutcome")
        with self._lock:
            current = self._assert_current_attempt(attempt)
            decision = self.decisions_by_ref.get(outcome.decision_ref)
            if decision is None:
                raise HarnessValidationError(
                    "side-effect outcome has no durable authorization"
                )
            _assert_outcome_matches_decision(outcome, decision)
            outcome = _bind_outcome_to_attempt(outcome, current)
            existing = self._existing_outcome(outcome)
            if existing is not None:
                return existing
            if current.status is HarnessSideEffectAttemptStatus.TERMINATED:
                raise _attempt_error(
                    "stale_side_effect_attempt",
                    "terminated side-effect attempt has no reconciled outcome",
                    effect_id=current.effect_id,
                    attempt_id=current.attempt_id,
                    fencing_generation=current.fencing_generation,
                )
            committed = self._persist_outcome(outcome)
            self._resolve_current_attempt(
                current,
                termination_confirmed=True,
                outcome_ref=committed.checksum,
            )
            return committed

    def get_outcome(
        self,
        *,
        effect_id: str,
        identity_scope_ref: str,
        subject_scope_ref: str,
        idempotency_key: str,
    ) -> HarnessSideEffectOutcome | None:
        with self._lock:
            outcome = self.outcomes_by_effect.get(effect_id)
            if outcome is None:
                return None
            _assert_scope(outcome, identity_scope_ref, subject_scope_ref)
            if outcome.idempotency_key != idempotency_key:
                raise HarnessValidationError(
                    "side-effect outcome idempotency identity mismatch"
                )
            return outcome

    def read_outcome(
        self,
        *,
        effect_id: str,
        identity_scope_ref: str,
        subject_scope_ref: str,
    ) -> HarnessSideEffectOutcome | None:
        with self._lock:
            outcome = self.outcomes_by_effect.get(effect_id)
            if outcome is None:
                return None
            _assert_scope(outcome, identity_scope_ref, subject_scope_ref)
            return outcome

    def get_decision(self, decision_ref: str) -> HarnessSideEffectDecision | None:
        with self._lock:
            return self.decisions_by_ref.get(decision_ref)

    def list_decisions(self, *, run_id: str) -> tuple[HarnessSideEffectDecision, ...]:
        with self._lock:
            return tuple(
                sorted(
                    (
                        decision
                        for decision in self.decisions_by_id.values()
                        if decision.run_id == run_id
                    ),
                    key=lambda decision: (
                        decision.command_ordinal,
                        decision.decision_id,
                    ),
                )
            )

    def reserve_attempt(
        self,
        decision: HarnessSideEffectDecision,
    ) -> int:
        if not isinstance(decision, HarnessSideEffectDecision):
            raise TypeError("decision must be HarnessSideEffectDecision")
        with self._lock:
            committed = self.decisions_by_ref.get(decision.checksum)
            if committed != decision:
                raise HarnessValidationError(
                    "handler attempt requires the exact durable authorization"
                )
            if decision.effect_id in self.attempt_leases_by_effect:
                raise _attempt_error(
                    "fenced_side_effect_attempt_required",
                    "fenced side-effect cannot use serial attempt reservation",
                    effect_id=decision.effect_id,
                )
            count = self.attempts_by_effect.get(decision.effect_id, 0)
            if count >= decision.effect_attempt_limit:
                raise _attempt_error(
                    "effect_retry_exhausted",
                    "side-effect retry budget is exhausted",
                    effect_id=decision.effect_id,
                    attempt_count=count,
                    attempt_limit=decision.effect_attempt_limit,
                )
            count += 1
            self.attempts_by_effect[decision.effect_id] = count
            return count

    def acquire_attempt(
        self,
        decision: HarnessSideEffectDecision,
        *,
        owner_id: str,
        lease_id: str,
    ) -> HarnessSideEffectAttemptLease:
        if not isinstance(decision, HarnessSideEffectDecision):
            raise TypeError("decision must be HarnessSideEffectDecision")
        with self._lock:
            committed = self.decisions_by_ref.get(decision.checksum)
            if committed != decision:
                raise HarnessValidationError(
                    "handler attempt requires the exact durable authorization"
                )
            existing_lease = self.attempt_leases_by_lease_id.get(lease_id)
            if existing_lease is not None:
                if (
                    existing_lease.owner_id != owner_id
                    or existing_lease.decision_ref != decision.checksum
                ):
                    raise _attempt_error(
                        "stale_side_effect_attempt",
                        "side-effect lease identity belongs to another owner or decision",
                        effect_id=decision.effect_id,
                        lease_id=lease_id,
                    )
                return existing_lease
            if decision.effect_id in self.outcomes_by_effect:
                raise _attempt_error(
                    "side_effect_outcome_already_committed",
                    "side-effect outcome is already committed",
                    effect_id=decision.effect_id,
                )
            count = self.attempts_by_effect.get(decision.effect_id, 0)
            current = self.attempt_leases_by_effect.get(decision.effect_id)
            if (
                current is not None
                and current.status is not HarnessSideEffectAttemptStatus.TERMINATED
            ):
                self._raise_attempt_overlap(current)
            if current is None and count:
                raise _attempt_error(
                    "side_effect_attempt_termination_unconfirmed",
                    "legacy side-effect attempt has no termination evidence",
                    effect_id=decision.effect_id,
                    attempt_count=count,
                    legacy_unfenced=True,
                )
            if count >= decision.effect_attempt_limit:
                raise _attempt_error(
                    "effect_retry_exhausted",
                    "side-effect retry budget is exhausted",
                    effect_id=decision.effect_id,
                    attempt_count=count,
                    attempt_limit=decision.effect_attempt_limit,
                )
            now = self._now()
            lease = HarnessSideEffectAttemptLease.create(
                decision,
                attempt=count + 1,
                owner_id=owner_id,
                lease_id=lease_id,
                acquired_at=now,
                lease_expires_at=now + timedelta(seconds=self.attempt_lease_seconds),
            )
            self.attempts_by_effect[decision.effect_id] = lease.attempt
            self.attempt_leases_by_effect[decision.effect_id] = lease
            self.attempt_leases_by_id[lease.attempt_id] = lease
            self.attempt_leases_by_lease_id[lease.lease_id] = lease
            return lease

    def get_attempt(
        self,
        *,
        effect_id: str,
        identity_scope_ref: str,
        subject_scope_ref: str,
    ) -> HarnessSideEffectAttemptLease | None:
        with self._lock:
            attempt = self.attempt_leases_by_effect.get(effect_id)
            if attempt is None:
                return None
            if (
                attempt.identity_scope_ref != identity_scope_ref
                or attempt.subject_scope_ref != subject_scope_ref
            ):
                raise HarnessValidationError("side-effect attempt scope mismatch")
            return attempt

    def renew_attempt(
        self,
        attempt: HarnessSideEffectAttemptLease,
    ) -> HarnessSideEffectAttemptLease:
        with self._lock:
            current = self._assert_current_attempt(attempt)
            self._assert_lease_accepts_result(current)
            now = self._now()
            next_expiry = now + timedelta(seconds=self.attempt_lease_seconds)
            if next_expiry <= current.lease_expires_at:
                return current
            renewed = current.renewed(lease_expires_at=next_expiry)
            self._replace_attempt(renewed)
            return renewed

    def finish_attempt(
        self,
        attempt: HarnessSideEffectAttemptLease,
        *,
        termination_confirmed: bool,
    ) -> HarnessSideEffectAttemptLease:
        with self._lock:
            current = self._assert_current_attempt(attempt)
            if current.status is HarnessSideEffectAttemptStatus.TERMINATED:
                if termination_confirmed:
                    return current
                raise HarnessValidationError(
                    "confirmed attempt termination cannot be revoked"
                )
            if (
                current.status is HarnessSideEffectAttemptStatus.INDETERMINATE
                and not termination_confirmed
            ):
                return current
            return self._resolve_current_attempt(
                current,
                termination_confirmed=termination_confirmed,
            )

    def attempt_count(
        self,
        *,
        effect_id: str,
        identity_scope_ref: str,
        subject_scope_ref: str,
    ) -> int:
        with self._lock:
            outcome = self.outcomes_by_effect.get(effect_id)
            if outcome is not None:
                _assert_scope(outcome, identity_scope_ref, subject_scope_ref)
            else:
                decisions = [
                    decision
                    for decision in self.decisions_by_id.values()
                    if decision.effect_id == effect_id
                ]
                if decisions and any(
                    decision.identity_scope_ref != identity_scope_ref
                    or decision.subject_scope_ref != subject_scope_ref
                    for decision in decisions
                ):
                    raise HarnessValidationError("side-effect attempt scope mismatch")
            return self.attempts_by_effect.get(effect_id, 0)

    def _existing_outcome(
        self,
        outcome: HarnessSideEffectOutcome,
    ) -> HarnessSideEffectOutcome | None:
        existing = self.outcomes_by_effect.get(outcome.effect_id)
        idempotent = self.outcomes_by_idempotency.get(outcome.idempotency_key)
        for candidate in (existing, idempotent):
            if candidate is None:
                continue
            if candidate != outcome:
                raise HarnessValidationError(
                    "side-effect outcome identity is immutable"
                )
            return candidate
        return None

    def _persist_outcome(
        self,
        outcome: HarnessSideEffectOutcome,
    ) -> HarnessSideEffectOutcome:
        existing = self._existing_outcome(outcome)
        if existing is not None:
            return existing
        self.outcomes_by_effect[outcome.effect_id] = outcome
        self.outcomes_by_idempotency[outcome.idempotency_key] = outcome
        self.outcome_write_count += 1
        return outcome

    def _assert_current_attempt(
        self,
        attempt: HarnessSideEffectAttemptLease,
    ) -> HarnessSideEffectAttemptLease:
        if not isinstance(attempt, HarnessSideEffectAttemptLease):
            raise TypeError("attempt must be HarnessSideEffectAttemptLease")
        current = self.attempt_leases_by_effect.get(attempt.effect_id)
        if current is None or not _same_attempt_generation(current, attempt):
            raise _attempt_error(
                "stale_side_effect_attempt",
                "side-effect attempt no longer owns the current fence",
                effect_id=attempt.effect_id,
                attempt_id=attempt.attempt_id,
                fencing_generation=attempt.fencing_generation,
            )
        return current

    def _assert_lease_accepts_result(
        self,
        attempt: HarnessSideEffectAttemptLease,
    ) -> None:
        if attempt.status is not HarnessSideEffectAttemptStatus.ACTIVE:
            raise _attempt_error(
                "stale_side_effect_attempt",
                "side-effect attempt is no longer active",
                effect_id=attempt.effect_id,
                attempt_id=attempt.attempt_id,
                fencing_generation=attempt.fencing_generation,
            )
        if self._now() >= attempt.lease_expires_at:
            raise _attempt_error(
                "side_effect_attempt_lease_expired",
                "side-effect attempt lease expired before the operation",
                effect_id=attempt.effect_id,
                attempt_id=attempt.attempt_id,
                fencing_generation=attempt.fencing_generation,
            )

    def _raise_attempt_overlap(self, attempt: HarnessSideEffectAttemptLease) -> None:
        code = (
            "side_effect_attempt_in_progress"
            if attempt.status is HarnessSideEffectAttemptStatus.ACTIVE
            and self._now() < attempt.lease_expires_at
            else "side_effect_attempt_termination_unconfirmed"
        )
        raise _attempt_error(
            code,
            "side-effect attempt cannot overlap an unconfirmed predecessor",
            effect_id=attempt.effect_id,
            attempt_id=attempt.attempt_id,
            fencing_generation=attempt.fencing_generation,
            lease_expired=self._now() >= attempt.lease_expires_at,
        )

    def _resolve_current_attempt(
        self,
        attempt: HarnessSideEffectAttemptLease,
        *,
        termination_confirmed: bool,
        outcome_ref: str | None = None,
    ) -> HarnessSideEffectAttemptLease:
        resolved = attempt.resolved(
            termination_confirmed=termination_confirmed,
            resolved_at=self._now(),
            outcome_ref=outcome_ref,
        )
        self._replace_attempt(resolved)
        return resolved

    def _replace_attempt(self, attempt: HarnessSideEffectAttemptLease) -> None:
        self.attempt_leases_by_effect[attempt.effect_id] = attempt
        self.attempt_leases_by_id[attempt.attempt_id] = attempt
        self.attempt_leases_by_lease_id[attempt.lease_id] = attempt

    def _now(self) -> datetime:
        return self._clock()

    def set_disposition(
        self,
        *,
        effect_id: str,
        disposition: HarnessSideEffectDisposition | str,
        identity_scope_ref: str,
        subject_scope_ref: str,
    ) -> HarnessSideEffectOutcome | None:
        with self._lock:
            outcome = self.outcomes_by_effect.get(effect_id)
            if outcome is None:
                return None
            _assert_scope(outcome, identity_scope_ref, subject_scope_ref)
            next_disposition = HarnessSideEffectDisposition(disposition)
            if outcome.disposition is next_disposition:
                return outcome
            if next_disposition is HarnessSideEffectDisposition.ACCEPTED:
                raise HarnessValidationError(
                    "generic disposition mutation cannot publish an effect"
                )
            updated = replace(
                outcome,
                disposition=next_disposition,
                public_refs=(),
                reason_code=f"disposition_{next_disposition.value}",
                checksum=None,
            )
            self.outcomes_by_effect[effect_id] = updated
            self.outcomes_by_idempotency[outcome.idempotency_key] = updated
            attempt = self.attempt_leases_by_effect.get(effect_id)
            if attempt is not None and attempt.outcome_ref == outcome.checksum:
                self._replace_attempt(attempt.relinked_outcome(updated.checksum))
            self.disposition_write_count += 1
            return updated


class CountingHarnessSideEffectHandler:
    """Idempotent fake that persists an outcome before returning it."""

    def __init__(
        self,
        store: InMemoryHarnessSideEffectStore,
        *,
        disposition: HarnessSideEffectDisposition
        | str = HarnessSideEffectDisposition.PREPARED,
        fail_before_outcome: bool = False,
        retention_seconds: int = 3600,
    ) -> None:
        self.store = store
        self.disposition = HarnessSideEffectDisposition(disposition)
        self.fail_before_outcome = bool(fail_before_outcome)
        self.retention_seconds = int(retention_seconds)
        self.call_count = 0
        self.effect_count = 0
        self.quarantine_count = 0

    def prepare(
        self,
        intent: HarnessSideEffectIntent,
        authorization: HarnessSideEffectDecision,
    ) -> HarnessSideEffectOutcome:
        return self.commit(intent, authorization)

    def commit(
        self,
        intent: HarnessSideEffectIntent,
        authorization: HarnessSideEffectDecision,
    ) -> HarnessSideEffectOutcome:
        self.call_count += 1
        _assert_intent_matches_decision(intent, authorization)
        existing = self.store.get_outcome(
            effect_id=intent.effect_id,
            identity_scope_ref=intent.identity_scope_ref,
            subject_scope_ref=intent.subject_scope_ref,
            idempotency_key=intent.idempotency_key,
        )
        if existing is not None:
            return existing
        if self.fail_before_outcome:
            raise RuntimeError("injected side-effect handler failure")
        public_refs = ()
        if self.disposition is HarnessSideEffectDisposition.ACCEPTED:
            public_refs = tuple(
                f"artifact://published/{ref.rsplit('/', 1)[-1]}"
                for ref in intent.candidate_refs
            )
            if not public_refs:
                public_refs = (f"effect://{intent.effect_id}",)
        committed_at = utc_now()
        retention_until = (
            committed_at + timedelta(seconds=self.retention_seconds)
            if self.disposition is HarnessSideEffectDisposition.PREPARED
            else None
        )
        outcome = HarnessSideEffectOutcome(
            outcome_id=f"harness-outcome:{intent.effect_id}",
            effect_id=intent.effect_id,
            decision_ref=authorization.checksum,
            run_id=intent.run_id,
            kind=intent.kind,
            handler=authorization.handler,
            idempotency_key=intent.idempotency_key,
            identity_scope_ref=intent.identity_scope_ref,
            subject_scope_ref=intent.subject_scope_ref,
            atomic_group=intent.atomic_group,
            disposition=self.disposition,
            candidate_refs=intent.candidate_refs,
            public_refs=public_refs,
            result_ref=checksum_for(
                {
                    "effect_id": intent.effect_id,
                    "candidate_refs": intent.candidate_refs,
                    "disposition": self.disposition.value,
                }
            ),
            retention_until=retention_until,
            metadata={"handler_call": self.call_count},
        )
        committed = self.store.put_outcome(outcome)
        self.effect_count += 1
        return committed

    def quarantine(
        self,
        intent: HarnessSideEffectIntent,
        authorization: HarnessSideEffectDecision,
    ) -> HarnessSideEffectOutcome | None:
        _assert_intent_matches_decision(intent, authorization)
        self.quarantine_count += 1
        return self.store.set_disposition(
            effect_id=intent.effect_id,
            disposition=HarnessSideEffectDisposition.QUARANTINE,
            identity_scope_ref=intent.identity_scope_ref,
            subject_scope_ref=intent.subject_scope_ref,
        )


def _assert_intent_matches_decision(
    intent: HarnessSideEffectIntent,
    decision: HarnessSideEffectDecision,
) -> None:
    if not isinstance(intent, HarnessSideEffectIntent) or not isinstance(
        decision,
        HarnessSideEffectDecision,
    ):
        raise TypeError("intent and decision must use Harness side-effect contracts")
    if (
        decision.intent_ref != intent.checksum
        or decision.effect_id != intent.effect_id
        or decision.run_id != intent.run_id
        or decision.kind != intent.kind
        or decision.origin is not intent.origin
        or decision.identity_scope_ref != intent.identity_scope_ref
        or decision.subject_scope_ref != intent.subject_scope_ref
        or decision.atomic_group != intent.atomic_group
        or decision.idempotency_key != intent.idempotency_key
    ):
        raise HarnessValidationError("side-effect authorization does not match intent")


def _assert_outcome_matches_decision(
    outcome: HarnessSideEffectOutcome,
    decision: HarnessSideEffectDecision,
) -> None:
    if (
        outcome.effect_id != decision.effect_id
        or outcome.run_id != decision.run_id
        or outcome.kind != decision.kind
        or outcome.handler != decision.handler
        or outcome.idempotency_key != decision.idempotency_key
        or outcome.identity_scope_ref != decision.identity_scope_ref
        or outcome.subject_scope_ref != decision.subject_scope_ref
        or outcome.atomic_group != decision.atomic_group
    ):
        raise HarnessValidationError("side-effect outcome does not match authorization")


def _assert_scope(
    outcome: HarnessSideEffectOutcome,
    identity_scope_ref: str,
    subject_scope_ref: str,
) -> None:
    if (
        outcome.identity_scope_ref != identity_scope_ref
        or outcome.subject_scope_ref != subject_scope_ref
    ):
        raise HarnessValidationError("side-effect outcome scope mismatch")


def _bind_outcome_to_attempt(
    outcome: HarnessSideEffectOutcome,
    attempt: HarnessSideEffectAttemptLease,
) -> HarnessSideEffectOutcome:
    if (
        outcome.effect_id != attempt.effect_id
        or outcome.decision_ref != attempt.decision_ref
        or outcome.idempotency_key != attempt.idempotency_key
        or outcome.identity_scope_ref != attempt.identity_scope_ref
        or outcome.subject_scope_ref != attempt.subject_scope_ref
    ):
        raise HarnessValidationError(
            "side-effect outcome attempt identity mismatch",
            code="side_effect_outcome_attempt_identity_mismatch",
        )
    if outcome.attempt_id is None:
        return replace(
            outcome,
            attempt_id=attempt.attempt_id,
            fencing_generation=attempt.fencing_generation,
            schema_version="newsroom.harness-side-effect-outcome/v2",
            checksum=None,
        )
    if (
        outcome.attempt_id != attempt.attempt_id
        or outcome.fencing_generation != attempt.fencing_generation
    ):
        raise _attempt_error(
            "stale_side_effect_attempt",
            "side-effect outcome carries a stale fencing identity",
            effect_id=outcome.effect_id,
            attempt_id=outcome.attempt_id,
            fencing_generation=outcome.fencing_generation,
        )
    return outcome


def _same_attempt_generation(
    left: HarnessSideEffectAttemptLease,
    right: HarnessSideEffectAttemptLease,
) -> bool:
    return (
        left.attempt_id == right.attempt_id
        and left.lease_id == right.lease_id
        and left.owner_id == right.owner_id
        and left.effect_id == right.effect_id
        and left.decision_ref == right.decision_ref
        and left.idempotency_key == right.idempotency_key
        and left.identity_scope_ref == right.identity_scope_ref
        and left.subject_scope_ref == right.subject_scope_ref
        and left.attempt == right.attempt
        and left.fencing_generation == right.fencing_generation
    )


def _attempt_error(code: str, message: str, **details: Any) -> HarnessValidationError:
    return HarnessValidationError(
        message,
        code=code,
        details={"code": code, **details},
    )


__all__ = [
    "CountingHarnessSideEffectHandler",
    "InMemoryHarnessSideEffectStore",
]
