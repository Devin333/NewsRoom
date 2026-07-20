from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Any

from framework.events.canonical import checksum_for
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.side_effects.models import (
    HarnessSideEffectDecision,
    HarnessSideEffectDisposition,
    HarnessSideEffectIntent,
    HarnessSideEffectOutcome,
)
from framework.shared.time import utc_now


class InMemoryHarnessSideEffectStore:
    """Counting contract store with exact scope and idempotency enforcement."""

    def __init__(self) -> None:
        self.decisions_by_ref: dict[str, HarnessSideEffectDecision] = {}
        self.decisions_by_id: dict[str, HarnessSideEffectDecision] = {}
        self.outcomes_by_effect: dict[str, HarnessSideEffectOutcome] = {}
        self.outcomes_by_idempotency: dict[str, HarnessSideEffectOutcome] = {}
        self.attempts_by_effect: dict[str, int] = {}
        self.decision_write_count = 0
        self.outcome_write_count = 0
        self.disposition_write_count = 0

    def put_decision(self, decision: HarnessSideEffectDecision) -> HarnessSideEffectDecision:
        if not isinstance(decision, HarnessSideEffectDecision):
            raise TypeError("decision must be HarnessSideEffectDecision")
        assert decision.checksum is not None
        existing = self.decisions_by_id.get(decision.decision_id)
        if existing is not None:
            if existing != decision:
                raise HarnessValidationError("side-effect decision identity is immutable")
            return existing
        by_ref = self.decisions_by_ref.get(decision.checksum)
        if by_ref is not None and by_ref != decision:
            raise HarnessValidationError("side-effect decision checksum collision")
        self.decisions_by_id[decision.decision_id] = decision
        self.decisions_by_ref[decision.checksum] = decision
        self.decision_write_count += 1
        return decision

    def put_outcome(self, outcome: HarnessSideEffectOutcome) -> HarnessSideEffectOutcome:
        if not isinstance(outcome, HarnessSideEffectOutcome):
            raise TypeError("outcome must be HarnessSideEffectOutcome")
        decision = self.decisions_by_ref.get(outcome.decision_ref)
        if decision is None:
            raise HarnessValidationError("side-effect outcome has no durable authorization")
        _assert_outcome_matches_decision(outcome, decision)
        existing = self.outcomes_by_effect.get(outcome.effect_id)
        idempotent = self.outcomes_by_idempotency.get(outcome.idempotency_key)
        for candidate in (existing, idempotent):
            if candidate is None:
                continue
            if candidate != outcome:
                raise HarnessValidationError("side-effect outcome identity is immutable")
            return candidate
        self.outcomes_by_effect[outcome.effect_id] = outcome
        self.outcomes_by_idempotency[outcome.idempotency_key] = outcome
        self.outcome_write_count += 1
        return outcome

    def get_outcome(
        self,
        *,
        effect_id: str,
        identity_scope_ref: str,
        subject_scope_ref: str,
        idempotency_key: str,
    ) -> HarnessSideEffectOutcome | None:
        outcome = self.outcomes_by_effect.get(effect_id)
        if outcome is None:
            return None
        _assert_scope(outcome, identity_scope_ref, subject_scope_ref)
        if outcome.idempotency_key != idempotency_key:
            raise HarnessValidationError("side-effect outcome idempotency identity mismatch")
        return outcome

    def read_outcome(
        self,
        *,
        effect_id: str,
        identity_scope_ref: str,
        subject_scope_ref: str,
    ) -> HarnessSideEffectOutcome | None:
        outcome = self.outcomes_by_effect.get(effect_id)
        if outcome is None:
            return None
        _assert_scope(outcome, identity_scope_ref, subject_scope_ref)
        return outcome

    def get_decision(self, decision_ref: str) -> HarnessSideEffectDecision | None:
        return self.decisions_by_ref.get(decision_ref)

    def list_decisions(self, *, run_id: str) -> tuple[HarnessSideEffectDecision, ...]:
        return tuple(
            sorted(
                (decision for decision in self.decisions_by_id.values() if decision.run_id == run_id),
                key=lambda decision: (decision.command_ordinal, decision.decision_id),
            )
        )

    def reserve_attempt(self, decision: HarnessSideEffectDecision) -> int:
        committed = self.decisions_by_ref.get(decision.checksum)
        if committed != decision:
            raise HarnessValidationError("handler attempt requires the exact durable authorization")
        count = self.attempts_by_effect.get(decision.effect_id, 0)
        if count >= decision.effect_attempt_limit:
            raise HarnessValidationError(
                "side-effect retry budget is exhausted",
                code="effect_retry_exhausted",
                details={
                    "code": "effect_retry_exhausted",
                    "effect_id": decision.effect_id,
                    "attempt_count": count,
                    "attempt_limit": decision.effect_attempt_limit,
                },
            )
        count += 1
        self.attempts_by_effect[decision.effect_id] = count
        return count

    def attempt_count(
        self,
        *,
        effect_id: str,
        identity_scope_ref: str,
        subject_scope_ref: str,
    ) -> int:
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

    def set_disposition(
        self,
        *,
        effect_id: str,
        disposition: HarnessSideEffectDisposition | str,
        identity_scope_ref: str,
        subject_scope_ref: str,
    ) -> HarnessSideEffectOutcome | None:
        outcome = self.outcomes_by_effect.get(effect_id)
        if outcome is None:
            return None
        _assert_scope(outcome, identity_scope_ref, subject_scope_ref)
        next_disposition = HarnessSideEffectDisposition(disposition)
        if outcome.disposition is next_disposition:
            return outcome
        if next_disposition is HarnessSideEffectDisposition.ACCEPTED:
            raise HarnessValidationError("generic disposition mutation cannot publish an effect")
        updated = replace(
            outcome,
            disposition=next_disposition,
            public_refs=(),
            reason_code=f"disposition_{next_disposition.value}",
            checksum=None,
        )
        self.outcomes_by_effect[effect_id] = updated
        self.outcomes_by_idempotency[outcome.idempotency_key] = updated
        self.disposition_write_count += 1
        return updated


class CountingHarnessSideEffectHandler:
    """Idempotent fake that persists an outcome before returning it."""

    def __init__(
        self,
        store: InMemoryHarnessSideEffectStore,
        *,
        disposition: HarnessSideEffectDisposition | str = HarnessSideEffectDisposition.PREPARED,
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
            public_refs = tuple(f"artifact://published/{ref.rsplit('/', 1)[-1]}" for ref in intent.candidate_refs)
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


__all__ = [
    "CountingHarnessSideEffectHandler",
    "InMemoryHarnessSideEffectStore",
]
