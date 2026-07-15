from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest

from framework.events import (
    AutomaticDeliveryOperation,
    ConsumerEffectContract,
    DurableSubscription,
    EffectIdempotencyCapability,
    EffectIdempotencyStrategy,
    EventConsumerIdempotencyError,
    IdempotencyCapabilityRegistry,
    effect_idempotency_key,
    subscription_definition_fingerprint,
)


VALIDATED_AT = datetime(2026, 7, 15, 11, 0, tzinfo=UTC)
BASE_OPERATIONS = frozenset(
    {
        AutomaticDeliveryOperation.INITIAL_DELIVERY,
        AutomaticDeliveryOperation.RETRY,
        AutomaticDeliveryOperation.LEASE_RECOVERY,
        AutomaticDeliveryOperation.REDELIVERY,
    }
)


def _subscription(
    *,
    external: bool = True,
    out_of_order: bool = False,
) -> DurableSubscription:
    effect = (
        ConsumerEffectContract(
            performs_external_effects=True,
            consumer_effect_id="search-index-write",
            idempotency_strategy=EffectIdempotencyStrategy.TARGET_IDEMPOTENCY_KEY,
        )
        if external
        else ConsumerEffectContract()
    )
    return DurableSubscription(
        subscription_id="search-index",
        subscription_version=2,
        consumer_id="search-indexer",
        effect=effect,
        supports_out_of_order_repair=out_of_order,
    )


def _capability(
    *,
    operations: frozenset[AutomaticDeliveryOperation] = BASE_OPERATIONS,
    consumer_effect_id: str = "search-index-write",
    subscription: DurableSubscription | None = None,
) -> EffectIdempotencyCapability:
    actual_subscription = subscription or _subscription()
    return EffectIdempotencyCapability(
        subscription_id="search-index",
        subscription_version=2,
        consumer_id="search-indexer",
        consumer_effect_id=consumer_effect_id,
        strategy=EffectIdempotencyStrategy.TARGET_IDEMPOTENCY_KEY,
        subscription_fingerprint=subscription_definition_fingerprint(
            actual_subscription
        ),
        validator_id="search-api-idempotency-header/v1",
        validated_at=VALIDATED_AT,
        supported_operations=operations,
    )


class _Validator:
    def __init__(self, capability: EffectIdempotencyCapability | None) -> None:
        self.capability = capability
        self.calls = 0

    def validate(self, subscription: DurableSubscription):
        self.calls += 1
        return self.capability


def test_activation_requires_real_capability_not_only_subscription_declaration() -> None:
    validator = _Validator(None)
    registry = IdempotencyCapabilityRegistry(validator)

    with pytest.raises(EventConsumerIdempotencyError, match="no verified"):
        registry.validate_for_activation(_subscription())

    assert validator.calls == 1


def test_matching_capability_is_cached_and_checked_for_each_operation() -> None:
    validator = _Validator(_capability())
    registry = IdempotencyCapabilityRegistry(validator)
    subscription = _subscription()

    activated = registry.validate_for_activation(subscription)
    retry = registry.require_for_delivery(
        subscription,
        AutomaticDeliveryOperation.RETRY,
    )
    recovered = registry.require_for_delivery(
        subscription,
        AutomaticDeliveryOperation.LEASE_RECOVERY,
    )

    assert activated == retry == recovered
    assert validator.calls == 1


def test_first_delivery_lazy_validation_is_thread_safe() -> None:
    validator = _Validator(_capability())
    registry = IdempotencyCapabilityRegistry(validator)
    subscription = _subscription()

    with ThreadPoolExecutor(max_workers=16) as executor:
        capabilities = list(
            executor.map(
                lambda _: registry.require_for_delivery(
                    subscription,
                    AutomaticDeliveryOperation.INITIAL_DELIVERY,
                ),
                range(32),
            )
        )

    assert all(capability == capabilities[0] for capability in capabilities)
    assert validator.calls == 1


def test_mismatched_or_incomplete_capability_fails_closed() -> None:
    mismatch = IdempotencyCapabilityRegistry(
        _Validator(_capability(consumer_effect_id="another-effect"))
    )
    with pytest.raises(EventConsumerIdempotencyError, match="does not match"):
        mismatch.validate_for_activation(_subscription())

    incomplete = IdempotencyCapabilityRegistry(
        _Validator(
            _capability(
                operations=frozenset(
                    {AutomaticDeliveryOperation.INITIAL_DELIVERY}
                )
            )
        )
    )
    with pytest.raises(EventConsumerIdempotencyError, match="incomplete"):
        incomplete.validate_for_activation(_subscription())


def test_out_of_order_requeue_requires_both_subscription_and_capability_support() -> None:
    no_repair = IdempotencyCapabilityRegistry(_Validator(_capability()))
    with pytest.raises(EventConsumerIdempotencyError, match="out-of-order"):
        no_repair.require_for_delivery(
            _subscription(out_of_order=False),
            AutomaticDeliveryOperation.REQUEUE,
        )

    operations = frozenset({*BASE_OPERATIONS, AutomaticDeliveryOperation.REQUEUE})
    repair_subscription = _subscription(out_of_order=True)
    repair = IdempotencyCapabilityRegistry(
        _Validator(
            _capability(
                operations=operations,
                subscription=repair_subscription,
            )
        )
    )
    capability = repair.validate_for_activation(repair_subscription)
    assert capability is not None
    assert AutomaticDeliveryOperation.REQUEUE in capability.supported_operations


def test_internal_consumer_never_requires_or_fabricates_effect_proof() -> None:
    validator = _Validator(None)
    registry = IdempotencyCapabilityRegistry(validator)
    subscription = _subscription(external=False)

    assert registry.validate_for_activation(subscription) is None
    assert registry.require_for_delivery(
        subscription,
        AutomaticDeliveryOperation.RETRY,
    ) is None
    assert validator.calls == 0


def test_effect_idempotency_key_ignores_delivery_and_subscription_generation() -> None:
    first = effect_idempotency_key("evt-1", "search-index-write")
    repeated = effect_idempotency_key("evt-1", "search-index-write")
    another_event = effect_idempotency_key("evt-2", "search-index-write")

    assert first == repeated
    assert first.startswith("newsroom-effect-v1:")
    assert first != another_event
    assert "evt-1" not in first


def test_capability_requires_timezone_aware_validation_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        EffectIdempotencyCapability(
            subscription_id="search-index",
            subscription_version=2,
            consumer_id="search-indexer",
            consumer_effect_id="search-index-write",
            strategy=EffectIdempotencyStrategy.TARGET_IDEMPOTENCY_KEY,
            subscription_fingerprint=subscription_definition_fingerprint(
                _subscription()
            ),
            validator_id="validator/v1",
            validated_at=datetime(2026, 7, 15, 11, 0),
            supported_operations=BASE_OPERATIONS,
        )
