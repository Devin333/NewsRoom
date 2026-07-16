from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from hashlib import sha256
from threading import RLock
from typing import Protocol, runtime_checkable

from framework.events.canonical import checksum_for
from framework.events.errors import EventConsumerIdempotencyError
from framework.events.runtime.models import (
    DurableSubscription,
    EffectIdempotencyStrategy,
    SubscriptionKey,
)


class AutomaticDeliveryOperation(str, Enum):
    INITIAL_DELIVERY = "initial_delivery"
    RETRY = "retry"
    LEASE_RECOVERY = "lease_recovery"
    REDELIVERY = "redelivery"
    REQUEUE = "requeue"


_BASE_REQUIRED_OPERATIONS = frozenset(
    {
        AutomaticDeliveryOperation.INITIAL_DELIVERY,
        AutomaticDeliveryOperation.RETRY,
        AutomaticDeliveryOperation.LEASE_RECOVERY,
        AutomaticDeliveryOperation.REDELIVERY,
    }
)


@dataclass(frozen=True, slots=True)
class EffectIdempotencyCapability:
    subscription_id: str
    subscription_version: int
    consumer_id: str
    consumer_effect_id: str
    strategy: EffectIdempotencyStrategy
    subscription_fingerprint: str
    validator_id: str
    validated_at: datetime
    supported_operations: frozenset[AutomaticDeliveryOperation]
    tenant_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "subscription_id",
            "consumer_id",
            "consumer_effect_id",
            "subscription_fingerprint",
            "validator_id",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )
        if (
            isinstance(self.subscription_version, bool)
            or not isinstance(self.subscription_version, int)
            or self.subscription_version < 1
        ):
            raise ValueError("subscription_version must be a positive integer")
        object.__setattr__(self, "strategy", EffectIdempotencyStrategy(self.strategy))
        object.__setattr__(self, "tenant_id", _optional_text(self.tenant_id, "tenant_id"))
        object.__setattr__(self, "validated_at", _utc(self.validated_at))
        if isinstance(self.supported_operations, (str, bytes)):
            raise TypeError("supported_operations must be a collection")
        object.__setattr__(
            self,
            "supported_operations",
            frozenset(
                AutomaticDeliveryOperation(operation)
                for operation in self.supported_operations
            ),
        )

    @property
    def subscription_key(self) -> SubscriptionKey:
        return SubscriptionKey(self.subscription_id, self.subscription_version)


@runtime_checkable
class ConsumerIdempotencyValidator(Protocol):
    """Composition-owned proof of a real effect idempotency boundary."""

    def validate(
        self,
        subscription: DurableSubscription,
    ) -> EffectIdempotencyCapability | None:
        ...


class IdempotencyCapabilityRegistry:
    """Fail-closed activation and first-delivery capability gate.

    A declaration on ``DurableSubscription`` is not proof.  Only a capability
    returned by the composed validator is cached, and every automatic delivery
    operation is checked against that immutable subscription version.
    """

    def __init__(self, validator: ConsumerIdempotencyValidator) -> None:
        self._validator = validator
        self._capabilities: dict[SubscriptionKey, EffectIdempotencyCapability] = {}
        self._lock = RLock()

    def validate_for_activation(
        self,
        subscription: DurableSubscription,
    ) -> EffectIdempotencyCapability | None:
        if not isinstance(subscription, DurableSubscription):
            raise TypeError("subscription must be DurableSubscription")
        if not subscription.effect.performs_external_effects:
            return None
        with self._lock:
            capability = self._validator.validate(subscription)
            self._assert_capability(subscription, capability)
            assert capability is not None
            self._capabilities[subscription.key] = capability
            return capability

    def require_for_delivery(
        self,
        subscription: DurableSubscription,
        operation: AutomaticDeliveryOperation,
    ) -> EffectIdempotencyCapability | None:
        if not isinstance(subscription, DurableSubscription):
            raise TypeError("subscription must be DurableSubscription")
        operation = AutomaticDeliveryOperation(operation)
        if not subscription.effect.performs_external_effects:
            return None
        if (
            operation
            in {
                AutomaticDeliveryOperation.REDELIVERY,
                AutomaticDeliveryOperation.REQUEUE,
            }
            and not subscription.supports_out_of_order_repair
        ):
            raise EventConsumerIdempotencyError(
                "subscription does not support idempotent out-of-order repair"
            )
        with self._lock:
            capability = self._capabilities.get(subscription.key)
            if capability is None:
                capability = self._validator.validate(subscription)
                self._assert_capability(subscription, capability)
                assert capability is not None
                self._capabilities[subscription.key] = capability
            else:
                self._assert_capability(subscription, capability)
            if operation not in capability.supported_operations:
                raise EventConsumerIdempotencyError(
                    f"idempotency capability does not cover {operation.value}"
                )
            return capability

    def revoke(self, key: SubscriptionKey) -> None:
        if not isinstance(key, SubscriptionKey):
            raise TypeError("key must be SubscriptionKey")
        with self._lock:
            self._capabilities.pop(key, None)

    def _assert_capability(
        self,
        subscription: DurableSubscription,
        capability: EffectIdempotencyCapability | None,
    ) -> None:
        if capability is None:
            raise EventConsumerIdempotencyError(
                "external-effect subscription has no verified idempotency capability"
            )
        effect = subscription.effect
        expected_effect_id = effect.consumer_effect_id
        expected_strategy = effect.idempotency_strategy
        if (
            capability.subscription_key != subscription.key
            or capability.consumer_id != subscription.consumer_id
            or capability.consumer_effect_id != expected_effect_id
            or capability.strategy != expected_strategy
            or capability.tenant_id != subscription.tenant_id
            or capability.subscription_fingerprint
            != subscription_definition_fingerprint(subscription)
        ):
            raise EventConsumerIdempotencyError(
                "idempotency capability does not match subscription definition"
            )
        required = set(_BASE_REQUIRED_OPERATIONS)
        if subscription.supports_out_of_order_repair:
            required.add(AutomaticDeliveryOperation.REQUEUE)
        missing = required - capability.supported_operations
        if missing:
            raise EventConsumerIdempotencyError(
                "idempotency capability is incomplete for automatic delivery"
            )


def effect_idempotency_key(event_id: str, consumer_effect_id: str) -> str:
    """Stable effect key independent of subscription version or delivery generation."""

    event_id = _required_text(event_id, "event_id")
    consumer_effect_id = _required_text(consumer_effect_id, "consumer_effect_id")
    digest = sha256(
        f"newsroom-effect-v1\0{event_id}\0{consumer_effect_id}".encode("utf-8")
    ).hexdigest()
    return f"newsroom-effect-v1:{digest}"


def subscription_definition_fingerprint(subscription: DurableSubscription) -> str:
    if not isinstance(subscription, DurableSubscription):
        raise TypeError("subscription must be DurableSubscription")
    return checksum_for(
        {
            "subscription_id": subscription.subscription_id,
            "subscription_version": subscription.subscription_version,
            "consumer_id": subscription.consumer_id,
            "tenant_id": subscription.tenant_id,
            "event_types": sorted(subscription.event_filter.event_types),
            "data_schemas": sorted(subscription.event_filter.data_schemas),
            "start_policy": subscription.start.policy.value,
            "start_sequence": subscription.start.start_sequence,
            "performs_external_effects": subscription.effect.performs_external_effects,
            "consumer_effect_id": subscription.effect.consumer_effect_id,
            "idempotency_strategy": (
                subscription.effect.idempotency_strategy.value
                if subscription.effect.idempotency_strategy is not None
                else None
            ),
            "supports_out_of_order_repair": subscription.supports_out_of_order_repair,
        }
    )


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field_name)


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("validated_at must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("validated_at must be timezone-aware")
    return value.astimezone(UTC)


__all__ = [
    "AutomaticDeliveryOperation",
    "ConsumerIdempotencyValidator",
    "EffectIdempotencyCapability",
    "IdempotencyCapabilityRegistry",
    "effect_idempotency_key",
    "subscription_definition_fingerprint",
]
