from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from framework.harness.waits.models import (
    HarnessSignalInboxEntry,
    HarnessWaitApprovalEvidenceRecord,
    HarnessWaitCancellationRecord,
    HarnessWaitRegistrationRecord,
    HarnessWaitResumeRecord,
    HarnessWaitScope,
    HarnessWaitSignal,
    HarnessWaitSignalMatch,
    HarnessWaitTimeoutRecord,
    HarnessWaitTimerWakeRecord,
)


@runtime_checkable
class HarnessSignalInboxPort(Protocol):
    """Durable, scope-authorized inbox for signals that may precede registration."""

    def put_signal(
        self,
        signal: HarnessWaitSignal,
        *,
        authorized_scope: HarnessWaitScope,
    ) -> HarnessSignalInboxEntry: ...

    def consume_matching(
        self,
        registration: HarnessWaitRegistrationRecord,
        *,
        matched_sequence: int,
    ) -> HarnessWaitSignalMatch | None: ...

    def get_match(
        self,
        registration_ref: str,
        *,
        authorized_scope: HarnessWaitScope,
    ) -> HarnessWaitSignalMatch | None: ...

    def prune_early_signals(self, *, through_sequence: int) -> tuple[str, ...]: ...


@runtime_checkable
class HarnessWaitRecordPort(Protocol):
    """Canonical-stream-backed persistence boundary for Wait facts."""

    def put_registration(
        self,
        registration: HarnessWaitRegistrationRecord,
    ) -> HarnessWaitRegistrationRecord: ...

    def get_registration(
        self,
        scope: HarnessWaitScope,
    ) -> HarnessWaitRegistrationRecord | None: ...

    def put_timer_wake(
        self,
        wake: HarnessWaitTimerWakeRecord,
    ) -> HarnessWaitTimerWakeRecord: ...

    def put_approval_evidence(
        self,
        evidence: HarnessWaitApprovalEvidenceRecord,
    ) -> HarnessWaitApprovalEvidenceRecord: ...

    def put_resume(
        self, resume: HarnessWaitResumeRecord
    ) -> HarnessWaitResumeRecord: ...

    def put_timeout(
        self,
        timeout: HarnessWaitTimeoutRecord,
    ) -> HarnessWaitTimeoutRecord: ...

    def put_cancellation(
        self,
        cancellation: HarnessWaitCancellationRecord,
    ) -> HarnessWaitCancellationRecord: ...


@runtime_checkable
class HarnessTimerWakePort(Protocol):
    """Outbound timer boundary; replay reads recorded wake facts instead."""

    def register_timer(
        self,
        registration: HarnessWaitRegistrationRecord,
    ) -> None: ...

    def cancel_timer(
        self,
        registration: HarnessWaitRegistrationRecord,
    ) -> None: ...


@runtime_checkable
class HarnessTimerDeadlineResolverPort(Protocol):
    """Resolve one persisted opaque deadline ref for live scheduling only."""

    def resolve_deadline(self, deadline_ref: str) -> datetime: ...


@runtime_checkable
class HarnessTimerWakeSinkPort(Protocol):
    """Submit a live timer wake to the canonical Wait-cause boundary."""

    def record_timer_wake(self, wake: HarnessWaitTimerWakeRecord) -> None: ...


@runtime_checkable
class HarnessWaitTimeoutSinkPort(Protocol):
    """Submit a live deadline timeout to the canonical Wait-cause boundary."""

    def record_wait_timeout(self, timeout: HarnessWaitTimeoutRecord) -> None: ...


HarnessWaitStorePort = HarnessWaitRecordPort


__all__ = [
    "HarnessSignalInboxPort",
    "HarnessTimerDeadlineResolverPort",
    "HarnessTimerWakePort",
    "HarnessTimerWakeSinkPort",
    "HarnessWaitTimeoutSinkPort",
    "HarnessWaitRecordPort",
    "HarnessWaitStorePort",
]
