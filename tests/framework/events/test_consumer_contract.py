from __future__ import annotations

from datetime import UTC, datetime

import pytest

from framework.events import (
    BusinessContext,
    ConsumerDeliveryContext,
    ConsumerDisposition,
    ConsumerFailureKind,
    ConsumerOutcome,
    DefaultConsumerErrorClassifier,
    DropAuthorizationRule,
    DurableSubscription,
    EventCandidate,
    PermanentEventProcessingError,
    ProducerIdentity,
    StaticDropAuthorizationPolicy,
    StoredEvent,
    failure_from_outcome,
)


def _event() -> StoredEvent:
    candidate = EventCandidate(
        event_id="evt-consumer-1",
        event_type="io.newsroom.test.consumer",
        data_schema="io.newsroom.test.consumer/v1",
        source="tests.consumer",
        occurred_at=datetime(2026, 7, 15, 9, 0, tzinfo=UTC),
        stream_id="run:consumer-1",
        business_context=BusinessContext(run_id="consumer-1"),
        producer=ProducerIdentity(component="consumer-test", version="1"),
        payload={"message": "ready"},
    )
    return StoredEvent(
        candidate,
        observed_at=datetime(2026, 7, 15, 9, 0, 1, tzinfo=UTC),
        stream_sequence=1,
    )


def _subscription() -> DurableSubscription:
    return DurableSubscription(
        subscription_id="search-index",
        subscription_version=1,
        consumer_id="search-indexer",
    )


def test_consumer_outcome_has_typed_ack_retry_and_drop_invariants() -> None:
    assert ConsumerOutcome.ack().disposition is ConsumerDisposition.ACK
    retry = ConsumerOutcome.retry("temporary_backend", "timeout_code")
    drop = ConsumerOutcome.drop("unsupported_event")

    assert retry.reason_class == "temporary_backend"
    assert drop.disposition is ConsumerDisposition.DROP
    with pytest.raises(ValueError, match="requires reason_class"):
        ConsumerOutcome(ConsumerDisposition.RETRY)
    with pytest.raises(ValueError, match="cannot include"):
        ConsumerOutcome(ConsumerDisposition.ACK, redacted_diagnostic="not-an-error")
    with pytest.raises(ValueError, match="2048"):
        ConsumerOutcome.retry("temporary_backend", "x" * 2_049)


def test_delivery_context_requires_effect_identity_and_idempotency_key_together() -> None:
    context = ConsumerDeliveryContext(
        delivery_id="delivery-1",
        subscription_id="search-index",
        subscription_version=1,
        delivery_generation=1,
        attempt_count=2,
        consumer_id="search-indexer",
        consumer_effect_id="search-index-write",
        idempotency_key="search-index-write:evt-consumer-1",
    )

    assert context.attempt_count == 2
    with pytest.raises(ValueError, match="both be set"):
        ConsumerDeliveryContext(
            delivery_id="delivery-1",
            subscription_id="search-index",
            subscription_version=1,
            delivery_generation=1,
            attempt_count=1,
            consumer_id="search-indexer",
            consumer_effect_id="search-index-write",
        )


def test_default_classifier_never_persists_arbitrary_exception_message() -> None:
    secret = "secret-token-must-not-leak"
    failure = DefaultConsumerErrorClassifier().classify(
        RuntimeError(f"backend failed with {secret}")
    )

    assert failure.kind is ConsumerFailureKind.TRANSIENT
    assert failure.reason_class == "unhandled_consumer_exception"
    assert failure.redacted_diagnostic == "RuntimeError"
    assert secret not in str(failure)


def test_typed_permanent_error_routes_directly_to_permanent_failure() -> None:
    failure = DefaultConsumerErrorClassifier().classify(
        PermanentEventProcessingError(
            "schema_semantically_unsupported",
            redacted_diagnostic="unsupported_version",
        )
    )

    assert failure.kind is ConsumerFailureKind.PERMANENT
    assert failure.reason_class == "schema_semantically_unsupported"


def test_drop_requires_explicit_consumer_event_and_reason_policy() -> None:
    event = _event()
    subscription = _subscription()
    outcome = ConsumerOutcome.drop("not_relevant")
    denied = StaticDropAuthorizationPolicy()
    allowed = StaticDropAuthorizationPolicy(
        [
            DropAuthorizationRule(
                reason_class="not_relevant",
                consumer_ids=frozenset({"search-indexer"}),
                event_types=frozenset({"io.newsroom.test.consumer"}),
            )
        ]
    )

    denied_failure = failure_from_outcome(
        outcome,
        subscription=subscription,
        event=event,
        drop_policy=denied,
    )
    allowed_failure = failure_from_outcome(
        outcome,
        subscription=subscription,
        event=event,
        drop_policy=allowed,
    )

    assert denied_failure is not None
    assert denied_failure.kind is ConsumerFailureKind.PERMANENT
    assert denied_failure.reason_class == "unapproved_drop"
    assert allowed_failure is None


def test_retry_outcome_is_transient_while_ack_has_no_failure() -> None:
    event = _event()
    subscription = _subscription()
    policy = StaticDropAuthorizationPolicy()

    assert failure_from_outcome(
        ConsumerOutcome.ack(),
        subscription=subscription,
        event=event,
        drop_policy=policy,
    ) is None
    failure = failure_from_outcome(
        ConsumerOutcome.retry("network_timeout", "timeout_code"),
        subscription=subscription,
        event=event,
        drop_policy=policy,
    )
    assert failure is not None
    assert failure.kind is ConsumerFailureKind.TRANSIENT

