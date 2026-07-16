from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from framework.events.errors import EventContractError, EventStoreUnavailableError
from framework.events.ports import EventStorePort
from framework.events.runtime.models import (
    CheckpointKey,
    ConsumerCheckpoint,
    DeadLetterAction,
    DeadLetterDisposition,
    DeadLetterPage,
    DeadLetterQuery,
    DeadLetterRecord,
    DeliveryRecord,
    PendingDeliveryStats,
    RedeliveryReport,
    RedeliveryRequest,
    SubscriptionKey,
)
from interfaces.services.event_reader_service import (
    EventAuthorizationContext,
    EventAuthorizerPort,
    EventPermission,
    EventServiceAvailability,
    authorize_event_operation,
)


class EventDeliveryRuntimePort(Protocol):
    def requeue_dead_letter(
        self,
        key: SubscriptionKey,
        action: DeadLetterAction,
    ) -> DeliveryRecord: ...

    def begin_redelivery(self, request: RedeliveryRequest) -> RedeliveryReport: ...


class EventOperationNotFoundError(LookupError):
    """An operator target is not visible in the authorized tenant scope."""


@dataclass(frozen=True, slots=True)
class DeadLetterLookupResult:
    availability: EventServiceAvailability
    tenant_id: str | None
    record: DeadLetterRecord | None = None
    unavailable_reason_class: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "availability", EventServiceAvailability(self.availability))
        if self.availability is EventServiceAvailability.AVAILABLE:
            if self.unavailable_reason_class is not None:
                raise ValueError("available dead-letter lookup has no failure reason")
        elif self.record is not None:
            raise ValueError("unavailable dead-letter lookup cannot contain a record")
        elif self.unavailable_reason_class is None:
            raise ValueError("unavailable dead-letter lookup requires a reason class")


@dataclass(frozen=True, slots=True)
class DeadLetterListResult:
    availability: EventServiceAvailability
    tenant_id: str | None
    page: DeadLetterPage | None = None
    unavailable_reason_class: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "availability", EventServiceAvailability(self.availability))
        if self.availability is EventServiceAvailability.AVAILABLE:
            if self.page is None:
                raise ValueError("available dead-letter list requires a page")
            if self.unavailable_reason_class is not None:
                raise ValueError("available dead-letter list has no failure reason")
        elif self.page is not None:
            raise ValueError("unavailable dead-letter list cannot contain a page")
        elif self.unavailable_reason_class is None:
            raise ValueError("unavailable dead-letter list requires a reason class")


@dataclass(frozen=True, slots=True)
class RedeliveryLookupResult:
    availability: EventServiceAvailability
    tenant_id: str | None
    report: RedeliveryReport | None = None
    unavailable_reason_class: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "availability", EventServiceAvailability(self.availability))
        if self.availability is EventServiceAvailability.AVAILABLE:
            if self.unavailable_reason_class is not None:
                raise ValueError("available redelivery lookup has no failure reason")
        elif self.report is not None:
            raise ValueError("unavailable redelivery lookup cannot contain a report")
        elif self.unavailable_reason_class is None:
            raise ValueError("unavailable redelivery lookup requires a reason class")


@dataclass(frozen=True, slots=True)
class ConsumerDeliveryStatusResult:
    availability: EventServiceAvailability
    subscription: SubscriptionKey
    stream_id: str
    tenant_id: str | None
    stats: PendingDeliveryStats | None = None
    checkpoint: ConsumerCheckpoint | None = None
    found: bool = True
    unavailable_reason_class: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "availability", EventServiceAvailability(self.availability))
        if self.availability is EventServiceAvailability.UNAVAILABLE:
            if self.stats is not None or self.checkpoint is not None:
                raise ValueError("unavailable delivery status cannot contain durable data")
            if self.unavailable_reason_class is None:
                raise ValueError("unavailable delivery status requires a reason class")
        elif self.unavailable_reason_class is not None:
            raise ValueError("available delivery status has no failure reason")
        elif not self.found and (self.stats is not None or self.checkpoint is not None):
            raise ValueError("missing subscription cannot contain delivery status")


class EventDeliveryOperationsService:
    """Authorized application operations over durable delivery state."""

    def __init__(
        self,
        *,
        store: EventStorePort,
        runtime: EventDeliveryRuntimePort,
        authorizer: EventAuthorizerPort,
    ) -> None:
        if store is None:
            raise ValueError("event store is required")
        if runtime is None:
            raise ValueError("durable delivery runtime is required")
        if authorizer is None:
            raise ValueError("event authorizer is required")
        self._store = store
        self._runtime = runtime
        self._authorizer = authorizer

    def get_dead_letter(
        self,
        dead_letter_id: str,
        *,
        authorization: EventAuthorizationContext,
    ) -> DeadLetterLookupResult:
        normalized_id = _required_text(dead_letter_id, "dead_letter_id")
        authorize_event_operation(
            self._authorizer,
            authorization,
            EventPermission.DEAD_LETTER_READ,
            target={"dead_letter_id": normalized_id},
        )
        try:
            record = self._store.get_dead_letter(
                normalized_id,
                tenant_id=authorization.tenant_id,
            )
        except EventStoreUnavailableError as error:
            return DeadLetterLookupResult(
                availability=EventServiceAvailability.UNAVAILABLE,
                tenant_id=authorization.tenant_id,
                unavailable_reason_class=type(error).__name__,
            )
        self._validate_dead_letter_scope(record, authorization)
        if record is not None and record.dead_letter_id != normalized_id:
            raise EventContractError("dead-letter store returned another target")
        return DeadLetterLookupResult(
            availability=EventServiceAvailability.AVAILABLE,
            tenant_id=authorization.tenant_id,
            record=record,
        )

    def list_dead_letters(
        self,
        *,
        authorization: EventAuthorizationContext,
        subscription_id: str | None = None,
        subscription_version: int | None = None,
        disposition: DeadLetterDisposition | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> DeadLetterListResult:
        query = DeadLetterQuery(
            subscription_id=subscription_id,
            subscription_version=subscription_version,
            tenant_id=authorization.tenant_id,
            disposition=disposition,
            cursor=cursor,
            limit=limit,
        )
        authorize_event_operation(
            self._authorizer,
            authorization,
            EventPermission.DEAD_LETTER_READ,
            target={
                "subscription_id": query.subscription_id,
                "subscription_version": query.subscription_version,
                "disposition": (
                    None if query.disposition is None else query.disposition.value
                ),
                "cursor": query.cursor,
                "limit": query.limit,
            },
        )
        try:
            page = self._store.list_dead_letters(query)
        except EventStoreUnavailableError as error:
            return DeadLetterListResult(
                availability=EventServiceAvailability.UNAVAILABLE,
                tenant_id=authorization.tenant_id,
                unavailable_reason_class=type(error).__name__,
            )
        if not isinstance(page, DeadLetterPage):
            raise EventContractError("dead-letter store returned an invalid page")
        if len(page.records) > query.limit:
            raise EventContractError("dead-letter store exceeded the requested limit")
        if page.next_cursor is not None and page.next_cursor == query.cursor:
            raise EventContractError("dead-letter cursor did not advance")
        if len({record.dead_letter_id for record in page.records}) != len(page.records):
            raise EventContractError("dead-letter store returned duplicate records")
        if any(
            record.tenant_id != authorization.tenant_id
            or (
                query.subscription_id is not None
                and record.subscription_id != query.subscription_id
            )
            or (
                query.subscription_version is not None
                and record.subscription_version != query.subscription_version
            )
            or (
                query.disposition is not None
                and record.disposition is not query.disposition
            )
            for record in page.records
        ):
            raise EventContractError("dead-letter store violated the query filters")
        return DeadLetterListResult(
            availability=EventServiceAvailability.AVAILABLE,
            tenant_id=authorization.tenant_id,
            page=page,
        )

    def requeue_dead_letter(
        self,
        subscription: SubscriptionKey,
        dead_letter_id: str,
        *,
        operator_reason: str,
        requested_at: datetime,
        idempotency_ready: bool,
        authorization: EventAuthorizationContext,
    ) -> DeliveryRecord:
        action = DeadLetterAction(
            dead_letter_id=dead_letter_id,
            operator_id=authorization.principal_id,
            reason=operator_reason,
            requested_at=requested_at,
            idempotency_ready=idempotency_ready,
        )
        authorize_event_operation(
            self._authorizer,
            authorization,
            EventPermission.DEAD_LETTER_REQUEUE,
            target={
                **_subscription_target(subscription),
                "dead_letter_id": action.dead_letter_id,
                "operator_reason": action.reason,
                "requested_at": action.requested_at.isoformat(),
                "idempotency_ready": action.idempotency_ready,
            },
        )
        definition = self._store.get_subscription(subscription)
        if not _subscription_matches(
            definition,
            subscription,
            tenant_id=authorization.tenant_id,
        ):
            raise EventOperationNotFoundError(
                "dead letter is not available in subscription scope"
            )
        scoped = self._store.get_dead_letter(
            action.dead_letter_id,
            tenant_id=authorization.tenant_id,
        )
        if (
            scoped is None
            or scoped.tenant_id != authorization.tenant_id
            or scoped.subscription_id != subscription.subscription_id
            or scoped.subscription_version != subscription.subscription_version
            or scoped.consumer_id != definition.consumer_id
            or scoped.consumer_effect_id != definition.effect.consumer_effect_id
        ):
            raise EventOperationNotFoundError(
                "dead letter is not available in subscription scope"
            )
        return self._runtime.requeue_dead_letter(subscription, action)

    def resolve_dead_letter(
        self,
        dead_letter_id: str,
        *,
        operator_reason: str,
        requested_at: datetime,
        authorization: EventAuthorizationContext,
    ) -> DeadLetterRecord:
        normalized_id = _required_text(dead_letter_id, "dead_letter_id")
        reason = _required_text(operator_reason, "operator_reason")
        authorize_event_operation(
            self._authorizer,
            authorization,
            EventPermission.DEAD_LETTER_RESOLVE,
            target={
                "dead_letter_id": normalized_id,
                "operator_reason": reason,
                "requested_at": requested_at.isoformat(),
            },
        )
        scoped = self._store.get_dead_letter(
            normalized_id,
            tenant_id=authorization.tenant_id,
        )
        if scoped is None:
            raise EventOperationNotFoundError("dead letter is not available in scope")
        self._validate_dead_letter_scope(scoped, authorization)
        action = DeadLetterAction(
            dead_letter_id=scoped.dead_letter_id,
            operator_id=authorization.principal_id,
            reason=reason,
            requested_at=requested_at,
        )
        resolved = self._store.resolve_dead_letter(action)
        self._validate_dead_letter_scope(resolved, authorization)
        if resolved.dead_letter_id != scoped.dead_letter_id:
            raise EventContractError("dead-letter store resolved another record")
        return resolved

    def begin_redelivery(
        self,
        *,
        redelivery_id: str,
        subscription: SubscriptionKey,
        source_stream_id: str,
        from_sequence: int,
        requested_at: datetime,
        operator_reason: str,
        authorization: EventAuthorizationContext,
        through_sequence: int | None = None,
    ) -> RedeliveryReport:
        reason = _required_text(operator_reason, "operator_reason")
        decision = authorize_event_operation(
            self._authorizer,
            authorization,
            EventPermission.REDELIVER,
            target={
                "redelivery_id": redelivery_id,
                **_subscription_target(subscription),
                "source_stream_id": source_stream_id,
                "from_sequence": from_sequence,
                "through_sequence": through_sequence,
                "requested_at": requested_at.isoformat(),
                "operator_reason": reason,
            },
        )
        request = RedeliveryRequest(
            redelivery_id=redelivery_id,
            subscription=subscription,
            source_stream_id=source_stream_id,
            from_sequence=from_sequence,
            through_sequence=through_sequence,
            requested_at=requested_at,
            operator_id=authorization.principal_id,
            operator_reason=reason,
            authorization_evidence_ref=decision.authorization_evidence_ref,
            tenant_id=authorization.tenant_id,
        )
        definition = self._store.get_subscription(subscription)
        if not _subscription_matches(
            definition,
            subscription,
            tenant_id=authorization.tenant_id,
        ):
            raise EventOperationNotFoundError(
                "subscription is not available in tenant scope"
            )
        report = self._runtime.begin_redelivery(request)
        if (
            not isinstance(report, RedeliveryReport)
            or report.redelivery_id != request.redelivery_id
            or report.subscription != request.subscription
            or report.source_stream_id != request.source_stream_id
            or report.from_sequence != request.from_sequence
            or report.requested_through_sequence != request.through_sequence
            or report.operator_id != request.operator_id
            or report.operator_reason != request.operator_reason
            or report.authorization_evidence_ref
            != request.authorization_evidence_ref
            or report.tenant_id != request.tenant_id
        ):
            raise EventContractError("delivery runtime returned another redelivery target")
        return report

    def get_redelivery_report(
        self,
        redelivery_id: str,
        *,
        authorization: EventAuthorizationContext,
    ) -> RedeliveryLookupResult:
        normalized_id = _required_text(redelivery_id, "redelivery_id")
        authorize_event_operation(
            self._authorizer,
            authorization,
            EventPermission.DELIVERY_STATUS_READ,
            target={"redelivery_id": normalized_id},
        )
        try:
            report = self._store.get_redelivery_report(
                normalized_id,
                tenant_id=authorization.tenant_id,
            )
        except EventStoreUnavailableError as error:
            return RedeliveryLookupResult(
                availability=EventServiceAvailability.UNAVAILABLE,
                tenant_id=authorization.tenant_id,
                unavailable_reason_class=type(error).__name__,
            )
        if report is not None and (
            not isinstance(report, RedeliveryReport)
            or report.redelivery_id != normalized_id
            or report.tenant_id != authorization.tenant_id
        ):
            raise EventContractError("redelivery store returned another target")
        return RedeliveryLookupResult(
            availability=EventServiceAvailability.AVAILABLE,
            tenant_id=authorization.tenant_id,
            report=report,
        )

    def get_consumer_status(
        self,
        subscription: SubscriptionKey,
        *,
        stream_id: str,
        authorization: EventAuthorizationContext,
    ) -> ConsumerDeliveryStatusResult:
        normalized_stream_id = _required_text(stream_id, "stream_id")
        authorize_event_operation(
            self._authorizer,
            authorization,
            EventPermission.DELIVERY_STATUS_READ,
            target={
                **_subscription_target(subscription),
                "stream_id": normalized_stream_id,
            },
        )
        try:
            definition = self._store.get_subscription(subscription)
            if not _subscription_matches(
                definition,
                subscription,
                tenant_id=authorization.tenant_id,
            ):
                return ConsumerDeliveryStatusResult(
                    availability=EventServiceAvailability.AVAILABLE,
                    subscription=subscription,
                    stream_id=normalized_stream_id,
                    tenant_id=authorization.tenant_id,
                    found=False,
                )
            stats = self._store.pending_delivery_stats(
                subscription,
                stream_id=normalized_stream_id,
            )
            checkpoint = self._store.get_checkpoint(
                CheckpointKey(
                    subscription_id=subscription.subscription_id,
                    subscription_version=subscription.subscription_version,
                    stream_id=normalized_stream_id,
                    tenant_id=authorization.tenant_id,
                ),
                tenant_id=authorization.tenant_id,
            )
        except EventStoreUnavailableError as error:
            return ConsumerDeliveryStatusResult(
                availability=EventServiceAvailability.UNAVAILABLE,
                subscription=subscription,
                stream_id=normalized_stream_id,
                tenant_id=authorization.tenant_id,
                found=False,
                unavailable_reason_class=type(error).__name__,
            )
        if checkpoint is not None and (
            checkpoint.tenant_id != authorization.tenant_id
            or checkpoint.subscription_id != subscription.subscription_id
            or checkpoint.subscription_version != subscription.subscription_version
            or checkpoint.stream_id != normalized_stream_id
        ):
            raise EventContractError("checkpoint store returned another target")
        return ConsumerDeliveryStatusResult(
            availability=EventServiceAvailability.AVAILABLE,
            subscription=subscription,
            stream_id=normalized_stream_id,
            tenant_id=authorization.tenant_id,
            stats=stats,
            checkpoint=checkpoint,
        )

    @staticmethod
    def _validate_dead_letter_scope(
        record: DeadLetterRecord | None,
        authorization: EventAuthorizationContext,
    ) -> None:
        if record is not None and record.tenant_id != authorization.tenant_id:
            raise EventContractError("dead-letter store crossed the tenant scope")


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def _subscription_target(subscription: SubscriptionKey) -> dict[str, Any]:
    if not isinstance(subscription, SubscriptionKey):
        raise TypeError("subscription must be SubscriptionKey")
    return {
        "subscription_id": subscription.subscription_id,
        "subscription_version": subscription.subscription_version,
    }


def _subscription_matches(
    definition: Any,
    subscription: SubscriptionKey,
    *,
    tenant_id: str | None,
) -> bool:
    return bool(
        definition is not None
        and getattr(definition, "subscription_id", None)
        == subscription.subscription_id
        and getattr(definition, "subscription_version", None)
        == subscription.subscription_version
        and getattr(definition, "tenant_id", None) == tenant_id
    )


__all__ = [
    "ConsumerDeliveryStatusResult",
    "DeadLetterListResult",
    "DeadLetterLookupResult",
    "EventDeliveryOperationsService",
    "EventDeliveryRuntimePort",
    "EventOperationNotFoundError",
    "RedeliveryLookupResult",
]
