from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from framework.events.canonical import StoredEvent
from framework.events.envelope import EventEnvelope

if TYPE_CHECKING:
    from framework.events.runtime.models import DurableSubscription


MAX_CONSUMER_DIAGNOSTIC_LENGTH = 2_048
MAX_CONSUMER_REASON_CLASS_LENGTH = 128


class EventSubscriber(Protocol):
    """Deprecated synchronous compatibility subscriber for legacy envelopes."""

    subscriber_id: str

    def handle(self, envelope: EventEnvelope) -> None:
        ...


@dataclass
class FunctionEventSubscriber:
    """Deprecated callable shim; durable consumers use ``DurableEventConsumer``."""

    callback: Callable[[EventEnvelope], None]
    subscriber_id: str = "function_subscriber"

    def handle(self, envelope: EventEnvelope) -> None:
        self.callback(envelope)


class ConsumerDisposition(str, Enum):
    ACK = "ack"
    RETRY = "retry"
    DROP = "drop"


@dataclass(frozen=True, slots=True)
class ConsumerOutcome:
    disposition: ConsumerDisposition
    reason_class: str | None = None
    redacted_diagnostic: str | None = None

    def __post_init__(self) -> None:
        disposition = ConsumerDisposition(self.disposition)
        reason = _optional_reason_class(self.reason_class)
        diagnostic = _diagnostic(self.redacted_diagnostic)
        if disposition in {ConsumerDisposition.RETRY, ConsumerDisposition.DROP}:
            if reason is None:
                raise ValueError(f"{disposition.value} outcome requires reason_class")
        if disposition is ConsumerDisposition.ACK and diagnostic is not None:
            raise ValueError("ACK outcome cannot include a failure diagnostic")
        object.__setattr__(self, "disposition", disposition)
        object.__setattr__(self, "reason_class", reason)
        object.__setattr__(self, "redacted_diagnostic", diagnostic)

    @classmethod
    def ack(cls, reason: str | None = None) -> ConsumerOutcome:
        return cls(ConsumerDisposition.ACK, reason_class=reason)

    @classmethod
    def retry(
        cls,
        reason_class: str,
        redacted_diagnostic: str | None = None,
    ) -> ConsumerOutcome:
        return cls(
            ConsumerDisposition.RETRY,
            reason_class=reason_class,
            redacted_diagnostic=redacted_diagnostic,
        )

    @classmethod
    def drop(
        cls,
        reason_class: str,
        redacted_diagnostic: str | None = None,
    ) -> ConsumerOutcome:
        return cls(
            ConsumerDisposition.DROP,
            reason_class=reason_class,
            redacted_diagnostic=redacted_diagnostic,
        )


@dataclass(frozen=True, slots=True)
class ConsumerDeliveryContext:
    delivery_id: str
    subscription_id: str
    subscription_version: int
    delivery_generation: int
    attempt_count: int
    consumer_id: str
    consumer_effect_id: str | None = None
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("delivery_id", "subscription_id", "consumer_id"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )
        for field_name in (
            "subscription_version",
            "delivery_generation",
            "attempt_count",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{field_name} must be a positive integer")
        effect_id = _optional_text(self.consumer_effect_id, "consumer_effect_id")
        idempotency_key = _optional_text(self.idempotency_key, "idempotency_key")
        if (effect_id is None) != (idempotency_key is None):
            raise ValueError(
                "consumer_effect_id and idempotency_key must both be set or absent"
            )
        object.__setattr__(self, "consumer_effect_id", effect_id)
        object.__setattr__(self, "idempotency_key", idempotency_key)


@runtime_checkable
class DurableEventConsumer(Protocol):
    consumer_id: str

    def consume(
        self,
        event: StoredEvent,
        context: ConsumerDeliveryContext,
    ) -> ConsumerOutcome:
        ...


class ConsumerFailureKind(str, Enum):
    TRANSIENT = "transient"
    PERMANENT = "permanent"


@dataclass(frozen=True, slots=True)
class ConsumerFailure:
    kind: ConsumerFailureKind
    reason_class: str
    redacted_diagnostic: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", ConsumerFailureKind(self.kind))
        object.__setattr__(
            self,
            "reason_class",
            _reason_class(self.reason_class),
        )
        object.__setattr__(
            self,
            "redacted_diagnostic",
            _diagnostic(self.redacted_diagnostic),
        )


class EventProcessingError(RuntimeError):
    failure_kind: ConsumerFailureKind

    def __init__(
        self,
        reason_class: str,
        *,
        redacted_diagnostic: str | None = None,
    ) -> None:
        self.reason_class = _reason_class(reason_class)
        self.redacted_diagnostic = _diagnostic(redacted_diagnostic)
        super().__init__(f"event processing failed: {self.reason_class}")


class TransientEventProcessingError(EventProcessingError):
    failure_kind = ConsumerFailureKind.TRANSIENT


class PermanentEventProcessingError(EventProcessingError):
    failure_kind = ConsumerFailureKind.PERMANENT


@runtime_checkable
class ConsumerErrorClassifier(Protocol):
    def classify(self, error: BaseException) -> ConsumerFailure:
        ...


class DefaultConsumerErrorClassifier:
    """Deterministic classifier that never persists an arbitrary exception message."""

    def classify(self, error: BaseException) -> ConsumerFailure:
        if isinstance(error, EventProcessingError):
            return ConsumerFailure(
                kind=error.failure_kind,
                reason_class=error.reason_class,
                redacted_diagnostic=error.redacted_diagnostic,
            )
        return ConsumerFailure(
            kind=ConsumerFailureKind.TRANSIENT,
            reason_class="unhandled_consumer_exception",
            redacted_diagnostic=type(error).__name__[:MAX_CONSUMER_DIAGNOSTIC_LENGTH],
        )


@dataclass(frozen=True, slots=True)
class DropAuthorizationRule:
    reason_class: str
    consumer_ids: frozenset[str] = frozenset()
    event_types: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "reason_class",
            _reason_class(self.reason_class),
        )
        object.__setattr__(
            self,
            "consumer_ids",
            _text_set(self.consumer_ids, "consumer_id"),
        )
        object.__setattr__(
            self,
            "event_types",
            _text_set(self.event_types, "event_type"),
        )

    def matches(
        self,
        *,
        subscription: DurableSubscription,
        event: StoredEvent,
        reason_class: str,
    ) -> bool:
        return (
            reason_class == self.reason_class
            and (not self.consumer_ids or subscription.consumer_id in self.consumer_ids)
            and (not self.event_types or event.event_type in self.event_types)
        )


@runtime_checkable
class DropAuthorizationPolicy(Protocol):
    def allows(
        self,
        *,
        subscription: DurableSubscription,
        event: StoredEvent,
        outcome: ConsumerOutcome,
    ) -> bool:
        ...


class StaticDropAuthorizationPolicy:
    """Explicit deterministic allowlist for non-error skip dispositions."""

    def __init__(self, rules: Iterable[DropAuthorizationRule] = ()) -> None:
        self._rules = tuple(rules)
        if any(not isinstance(rule, DropAuthorizationRule) for rule in self._rules):
            raise TypeError("drop authorization rules must be DropAuthorizationRule")

    def allows(
        self,
        *,
        subscription: DurableSubscription,
        event: StoredEvent,
        outcome: ConsumerOutcome,
    ) -> bool:
        if outcome.disposition is not ConsumerDisposition.DROP:
            return False
        assert outcome.reason_class is not None
        return any(
            rule.matches(
                subscription=subscription,
                event=event,
                reason_class=outcome.reason_class,
            )
            for rule in self._rules
        )


def failure_from_outcome(
    outcome: ConsumerOutcome,
    *,
    subscription: DurableSubscription,
    event: StoredEvent,
    drop_policy: DropAuthorizationPolicy,
) -> ConsumerFailure | None:
    """Return a failure for RETRY or an unauthorized DROP; ACK/allowed DROP are terminal."""

    if outcome.disposition is ConsumerDisposition.ACK:
        return None
    if outcome.disposition is ConsumerDisposition.DROP:
        if drop_policy.allows(
            subscription=subscription,
            event=event,
            outcome=outcome,
        ):
            return None
        return ConsumerFailure(
            kind=ConsumerFailureKind.PERMANENT,
            reason_class="unapproved_drop",
            redacted_diagnostic="drop_policy_denied",
        )
    assert outcome.reason_class is not None
    return ConsumerFailure(
        kind=ConsumerFailureKind.TRANSIENT,
        reason_class=outcome.reason_class,
        redacted_diagnostic=outcome.redacted_diagnostic,
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


def _diagnostic(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("redacted_diagnostic must be a string")
    normalized = value.strip()
    if len(normalized) > MAX_CONSUMER_DIAGNOSTIC_LENGTH:
        raise ValueError("redacted_diagnostic exceeds the 2048 character limit")
    return normalized or None


def _optional_reason_class(value: object) -> str | None:
    if value is None:
        return None
    return _reason_class(value)


def _reason_class(value: object) -> str:
    normalized = _required_text(value, "reason_class")
    if len(normalized) > MAX_CONSUMER_REASON_CLASS_LENGTH:
        raise ValueError(
            "reason_class exceeds the "
            f"{MAX_CONSUMER_REASON_CLASS_LENGTH} character limit"
        )
    return normalized


def _text_set(values: Iterable[str], field_name: str) -> frozenset[str]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{field_name}s must be a collection")
    return frozenset(_required_text(value, field_name) for value in values)


__all__ = [
    "ConsumerDeliveryContext",
    "ConsumerDisposition",
    "ConsumerErrorClassifier",
    "ConsumerFailure",
    "ConsumerFailureKind",
    "ConsumerOutcome",
    "DefaultConsumerErrorClassifier",
    "DropAuthorizationPolicy",
    "DropAuthorizationRule",
    "DurableEventConsumer",
    "EventProcessingError",
    "EventSubscriber",
    "FunctionEventSubscriber",
    "MAX_CONSUMER_DIAGNOSTIC_LENGTH",
    "MAX_CONSUMER_REASON_CLASS_LENGTH",
    "PermanentEventProcessingError",
    "StaticDropAuthorizationPolicy",
    "TransientEventProcessingError",
    "failure_from_outcome",
]
