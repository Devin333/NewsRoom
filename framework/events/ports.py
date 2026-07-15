from __future__ import annotations

from datetime import datetime
from types import TracebackType
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from framework.events.runtime.models import (
    AppendResult,
    CheckpointKey,
    CheckpointPage,
    CheckpointQuery,
    ClaimedDelivery,
    ConsumerCheckpoint,
    DeadLetterAction,
    DeadLetterPage,
    DeadLetterQuery,
    DeadLetterRecord,
    DeliveryClaimRequest,
    DeliveryLeaseToken,
    DeliveryPage,
    DeliveryQuery,
    DeliveryRecord,
    DeliverySettlement,
    DeliverySettlementResult,
    DurableSubscription,
    EventPage,
    InboxEntry,
    InboxKey,
    PendingDeliveryStats,
    QuarantineDisposition,
    QuarantinePage,
    QuarantineQuery,
    QuarantineRecord,
    ReplayReport,
    ReplayReportPage,
    ReplayReportQuery,
    ReplayStartRequest,
    StreamReadRequest,
    SubscriptionKey,
    SubscriptionPage,
    SubscriptionQuery,
    SubscriptionStreamState,
    SubscriptionStreamStatePage,
    SubscriptionStreamStateQuery,
    SubscriptionStatus,
)

if TYPE_CHECKING:
    from framework.events.canonical import EventCandidate, StoredEvent
    from framework.events.runtime.publisher import EventPublishRequest


@runtime_checkable
class EventUnitOfWorkPort(Protocol):
    """Backend-neutral transaction boundary for event/outbox mutations.

    ``append_event`` allocates the observation time and 1-based stream sequence,
    persists the immutable event, and materializes every matching pending
    delivery in this unit of work.  No part is externally visible before
    ``commit``.  A duplicate event identity with equal content returns the
    original event and creates no new delivery rows.  ``commit`` is explicit;
    leaving the context without committing must roll back staged changes.
    """

    def append_event(self, event: EventCandidate) -> AppendResult: ...

    def settle_delivery(
        self,
        settlement: DeliverySettlement,
    ) -> DeliverySettlementResult:
        """Fence and settle one claim, including inbox/checkpoint/DLQ changes."""
        ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def __enter__(self) -> EventUnitOfWorkPort: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...


@runtime_checkable
class EventReaderPort(Protocol):
    """Authoritative reads ordered within ``(tenant_id, stream_id)`` only."""

    def get_event(
        self,
        event_id: str,
        *,
        tenant_id: str | None = None,
    ) -> StoredEvent | None:
        """Look up the globally stable event identity within caller scope."""
        ...

    def read_stream(self, request: StreamReadRequest) -> EventPage:
        """Return an ascending sequence page after the exclusive cursor."""
        ...

    def get_stream_high_watermark(
        self,
        stream_id: str,
        *,
        tenant_id: str | None = None,
    ) -> int | None:
        """Return the last committed 1-based sequence, or ``None`` if empty."""
        ...


@runtime_checkable
class DurableSubscriptionStorePort(Protocol):
    """Durable versioned subscriptions and their registration boundary."""

    def register_subscription(
        self,
        subscription: DurableSubscription,
    ) -> DurableSubscription:
        """Atomically fix the start watermark and materialize retained work."""
        ...

    def get_subscription(self, key: SubscriptionKey) -> DurableSubscription | None: ...

    def list_subscriptions(self, query: SubscriptionQuery) -> SubscriptionPage: ...

    def get_subscription_stream_state(
        self,
        key: SubscriptionKey,
        stream_id: str,
        *,
        tenant_id: str | None = None,
    ) -> SubscriptionStreamState | None: ...

    def list_subscription_stream_states(
        self,
        query: SubscriptionStreamStateQuery,
    ) -> SubscriptionStreamStatePage: ...

    def set_subscription_status(
        self,
        key: SubscriptionKey,
        status: SubscriptionStatus,
        *,
        changed_at: datetime,
        reason: str,
    ) -> DurableSubscription:
        """Pause/resume or transactionally fix per-stream retirement watermarks."""
        ...


@runtime_checkable
class EventDeliveryLedgerPort(Protocol):
    """Pending delivery, leased claims, fencing, and terminal transitions."""

    def get_delivery(
        self,
        delivery_id: str,
        *,
        tenant_id: str | None = None,
    ) -> DeliveryRecord | None: ...

    def list_deliveries(self, query: DeliveryQuery) -> DeliveryPage: ...

    def claim_deliveries(
        self,
        request: DeliveryClaimRequest,
    ) -> tuple[ClaimedDelivery, ...]:
        """Claim bounded ordered work and recover eligible expired leases."""
        ...

    def renew_delivery_lease(
        self,
        lease: DeliveryLeaseToken,
        *,
        renewed_at: datetime,
        lease_duration_seconds: float,
    ) -> DeliveryLeaseToken:
        """Renew only the currently owned fencing generation."""
        ...

    def settle_delivery(
        self,
        settlement: DeliverySettlement,
    ) -> DeliverySettlementResult:
        """Atomically update delivery, inbox, contiguous checkpoint, and DLQ."""
        ...

    def pending_delivery_stats(
        self,
        key: SubscriptionKey,
        *,
        stream_id: str | None = None,
    ) -> PendingDeliveryStats: ...


@runtime_checkable
class EventInboxStorePort(Protocol):
    """Read access to effect-level idempotency records.

    Inbox writes occur only through a delivery settlement/effect transaction;
    a standalone write method would not prove external-effect atomicity.
    """

    def get_inbox_entry(
        self,
        key: InboxKey,
        *,
        tenant_id: str | None = None,
    ) -> InboxEntry | None: ...


@runtime_checkable
class ConsumerCheckpointStorePort(Protocol):
    """Subscription-version contiguous frontiers, never legacy offsets."""

    def get_checkpoint(
        self,
        key: CheckpointKey,
        *,
        tenant_id: str | None = None,
    ) -> ConsumerCheckpoint | None: ...

    def list_checkpoints(self, query: CheckpointQuery) -> CheckpointPage: ...


@runtime_checkable
class DeadLetterStorePort(Protocol):
    def get_dead_letter(
        self,
        dead_letter_id: str,
        *,
        tenant_id: str | None = None,
    ) -> DeadLetterRecord | None: ...

    def list_dead_letters(self, query: DeadLetterQuery) -> DeadLetterPage: ...

    def requeue_dead_letter(self, action: DeadLetterAction) -> DeliveryRecord:
        """Create a new late-repair delivery generation without rewinding."""
        ...

    def resolve_dead_letter(self, action: DeadLetterAction) -> DeadLetterRecord: ...


@runtime_checkable
class QuarantineStorePort(Protocol):
    def save_quarantine(self, record: QuarantineRecord) -> QuarantineRecord: ...

    def get_quarantine(
        self,
        quarantine_id: str,
        *,
        tenant_id: str | None = None,
    ) -> QuarantineRecord | None: ...

    def list_quarantine(self, query: QuarantineQuery) -> QuarantinePage: ...

    def resolve_quarantine(
        self,
        quarantine_id: str,
        disposition: QuarantineDisposition,
        *,
        operator_id: str,
        reason: str,
        resolved_at: datetime,
    ) -> QuarantineRecord: ...


@runtime_checkable
class ReplayReportStorePort(Protocol):
    """Replay audit access isolated from the immutable source stream."""

    def begin_replay(self, request: ReplayStartRequest) -> ReplayReport:
        """Atomically capture a finite source watermark and create its report."""
        ...

    def update_replay_report(self, report: ReplayReport) -> ReplayReport: ...

    def get_replay_report(
        self,
        replay_id: str,
        *,
        tenant_id: str | None = None,
    ) -> ReplayReport | None: ...

    def list_replay_reports(self, query: ReplayReportQuery) -> ReplayReportPage: ...


@runtime_checkable
class EventStorePort(
    EventReaderPort,
    DurableSubscriptionStorePort,
    EventDeliveryLedgerPort,
    EventInboxStorePort,
    ConsumerCheckpointStorePort,
    DeadLetterStorePort,
    QuarantineStorePort,
    ReplayReportStorePort,
    Protocol,
):
    """One conformance surface shared by SQLite and PostgreSQL adapters."""

    def unit_of_work(self) -> EventUnitOfWorkPort: ...


@runtime_checkable
class EventRuntimePort(Protocol):
    """Canonical publish boundary; dispatch is never part of this call."""

    def publish(
        self,
        event: EventPublishRequest,
        *,
        unit_of_work: EventUnitOfWorkPort | None = None,
    ) -> StoredEvent:
        """Return the accepted stored event, committing unless a UoW is supplied."""
        ...


__all__ = [
    "ConsumerCheckpointStorePort",
    "DeadLetterStorePort",
    "DurableSubscriptionStorePort",
    "EventDeliveryLedgerPort",
    "EventInboxStorePort",
    "EventReaderPort",
    "EventRuntimePort",
    "EventStorePort",
    "EventUnitOfWorkPort",
    "QuarantineStorePort",
    "ReplayReportStorePort",
]
