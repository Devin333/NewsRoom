from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from framework.events.runtime.idempotency import subscription_definition_fingerprint
from framework.events.runtime.models import (
    ClaimedDelivery,
    DeliverySettlementResult,
    DeliveryState,
    DurableSubscription,
    EffectIdempotencyStrategy,
    SubscriptionKey,
)
from framework.events.subscriber import (
    ConsumerDeliveryContext,
    ConsumerDisposition,
    ConsumerOutcome,
    DurableEventConsumer,
)


@dataclass(frozen=True, slots=True)
class InboxTransactionCapability:
    subscription_id: str
    subscription_version: int
    consumer_id: str
    consumer_effect_id: str
    subscription_fingerprint: str
    runner_id: str
    validated_at: datetime

    def __post_init__(self) -> None:
        key = SubscriptionKey(self.subscription_id, self.subscription_version)
        object.__setattr__(self, "subscription_id", key.subscription_id)
        object.__setattr__(self, "subscription_version", key.subscription_version)
        for field_name in (
            "consumer_id",
            "consumer_effect_id",
            "subscription_fingerprint",
            "runner_id",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "validated_at",
            _utc(self.validated_at, "validated_at"),
        )

    @property
    def subscription_key(self) -> SubscriptionKey:
        return SubscriptionKey(self.subscription_id, self.subscription_version)


@dataclass(frozen=True, slots=True)
class InboxTransactionResult:
    """Result of one composition-owned effect/inbox/settlement transaction."""

    consumer_called: bool
    inbox_already_completed: bool
    outcome: ConsumerOutcome | None = None
    settlement: DeliverySettlementResult | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.consumer_called, bool):
            raise TypeError("consumer_called must be a boolean")
        if not isinstance(self.inbox_already_completed, bool):
            raise TypeError("inbox_already_completed must be a boolean")
        if self.outcome is not None and not isinstance(self.outcome, ConsumerOutcome):
            raise TypeError("outcome must be ConsumerOutcome")
        if self.settlement is not None and not isinstance(
            self.settlement,
            DeliverySettlementResult,
        ):
            raise TypeError("settlement must be DeliverySettlementResult")
        if self.inbox_already_completed and self.consumer_called:
            raise ValueError("completed inbox must bypass the consumer effect")
        if self.settlement is not None:
            if self.settlement.delivery.state is not DeliveryState.ACKED:
                raise ValueError("inbox transaction may commit only an ACK settlement")
            if (
                self.outcome is not None
                and self.outcome.disposition is not ConsumerDisposition.ACK
            ):
                raise ValueError("committed inbox transaction outcome must be ACK")
        elif self.outcome is None:
            raise ValueError("unsettled inbox transaction requires a consumer outcome")
        elif self.outcome.disposition is ConsumerDisposition.ACK:
            raise ValueError("ACK requires atomic inbox and delivery settlement")


@runtime_checkable
class InboxTransactionalEffectRunner(Protocol):
    """Composition-owned transaction joining effect, inbox, and ACK settlement.

    ``execute`` MUST inspect/insert ``(event_id, consumer_effect_id)``, invoke the
    business effect, and settle ACK through one real transaction.  Any error or
    non-ACK outcome MUST roll back the business effect and inbox together before
    returning or raising.  Merely calling ``EventStorePort.settle_delivery``
    after the consumer returns does not satisfy this protocol.
    """

    runner_id: str

    def validate(
        self,
        subscription: DurableSubscription,
    ) -> InboxTransactionCapability | None:
        ...

    def execute(
        self,
        *,
        subscription: DurableSubscription,
        consumer: DurableEventConsumer,
        claimed: ClaimedDelivery,
        context: ConsumerDeliveryContext,
        settled_at: datetime,
    ) -> InboxTransactionResult:
        ...


def validate_inbox_transaction_capability(
    subscription: DurableSubscription,
    runner: InboxTransactionalEffectRunner | None,
) -> InboxTransactionCapability:
    if (
        subscription.effect.idempotency_strategy
        is not EffectIdempotencyStrategy.INBOX_TRANSACTION
    ):
        raise ValueError("subscription does not use INBOX_TRANSACTION")
    if runner is None:
        raise ValueError(
            "INBOX_TRANSACTION requires a composed transactional effect runner"
        )
    validation_failed = False
    try:
        capability = runner.validate(subscription)
    except Exception:
        validation_failed = True
        capability = None
    if validation_failed:
        raise ValueError("transactional effect runner validation failed")
    if capability is None:
        raise ValueError(
            "transactional effect runner did not validate the subscription"
        )
    expected_effect_id = subscription.effect.consumer_effect_id
    if (
        capability.subscription_key != subscription.key
        or capability.consumer_id != subscription.consumer_id
        or capability.consumer_effect_id != expected_effect_id
        or capability.subscription_fingerprint
        != subscription_definition_fingerprint(subscription)
        or capability.runner_id != _required_text(runner.runner_id, "runner_id")
    ):
        raise ValueError(
            "transactional effect capability does not match subscription definition"
        )
    return capability


def _utc(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


__all__ = [
    "InboxTransactionCapability",
    "InboxTransactionResult",
    "InboxTransactionalEffectRunner",
    "validate_inbox_transaction_capability",
]
