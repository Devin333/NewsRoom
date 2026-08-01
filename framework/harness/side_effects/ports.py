from __future__ import annotations

from typing import Protocol, runtime_checkable

from framework.harness.side_effects.models import (
    HarnessSideEffectAttemptLease,
    HarnessSideEffectDecision,
    HarnessSideEffectDisposition,
    HarnessSideEffectIntent,
    HarnessSideEffectOutcome,
)


@runtime_checkable
class HarnessSideEffectStorePort(Protocol):
    def put_decision(
        self, decision: HarnessSideEffectDecision
    ) -> HarnessSideEffectDecision: ...

    def put_outcome(
        self, outcome: HarnessSideEffectOutcome
    ) -> HarnessSideEffectOutcome: ...

    def get_outcome(
        self,
        *,
        effect_id: str,
        identity_scope_ref: str,
        subject_scope_ref: str,
        idempotency_key: str,
    ) -> HarnessSideEffectOutcome | None: ...

    def get_decision(self, decision_ref: str) -> HarnessSideEffectDecision | None: ...

    def list_decisions(
        self, *, run_id: str
    ) -> tuple[HarnessSideEffectDecision, ...]: ...

    def reserve_attempt(
        self,
        decision: HarnessSideEffectDecision,
    ) -> int:
        """Persist the next serial handler-attempt number for one authorization."""
        ...

    def attempt_count(
        self,
        *,
        effect_id: str,
        identity_scope_ref: str,
        subject_scope_ref: str,
    ) -> int: ...

    def set_disposition(
        self,
        *,
        effect_id: str,
        disposition: HarnessSideEffectDisposition | str,
        identity_scope_ref: str,
        subject_scope_ref: str,
    ) -> HarnessSideEffectOutcome | None: ...


@runtime_checkable
class HarnessFencedSideEffectStorePort(HarnessSideEffectStorePort, Protocol):
    def acquire_attempt(
        self,
        decision: HarnessSideEffectDecision,
        *,
        owner_id: str,
        lease_id: str,
    ) -> HarnessSideEffectAttemptLease: ...

    def get_attempt(
        self,
        *,
        effect_id: str,
        identity_scope_ref: str,
        subject_scope_ref: str,
    ) -> HarnessSideEffectAttemptLease | None: ...

    def renew_attempt(
        self,
        attempt: HarnessSideEffectAttemptLease,
    ) -> HarnessSideEffectAttemptLease: ...

    def finish_attempt(
        self,
        attempt: HarnessSideEffectAttemptLease,
        *,
        termination_confirmed: bool,
    ) -> HarnessSideEffectAttemptLease: ...

    def complete_attempt(
        self,
        attempt: HarnessSideEffectAttemptLease,
        outcome: HarnessSideEffectOutcome,
    ) -> HarnessSideEffectOutcome: ...

    def reconcile_attempt(
        self,
        attempt: HarnessSideEffectAttemptLease,
        outcome: HarnessSideEffectOutcome,
    ) -> HarnessSideEffectOutcome: ...


@runtime_checkable
class HarnessSideEffectReaderPort(Protocol):
    def read_outcome(
        self,
        *,
        effect_id: str,
        identity_scope_ref: str,
        subject_scope_ref: str,
    ) -> HarnessSideEffectOutcome | None: ...


@runtime_checkable
class HarnessSideEffectHandlerContext(Protocol):
    """Optional narrow context passed by composition roots to handlers."""

    def prepare_candidate(
        self, intent: HarnessSideEffectIntent
    ) -> HarnessSideEffectOutcome: ...


__all__ = [
    "HarnessFencedSideEffectStorePort",
    "HarnessSideEffectHandlerContext",
    "HarnessSideEffectReaderPort",
    "HarnessSideEffectStorePort",
]
