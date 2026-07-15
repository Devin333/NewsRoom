from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from threading import RLock
from typing import TYPE_CHECKING, Final, TypeVar

from framework.events.errors import (
    EventConsumerIdempotencyError,
    EventDeliveryError,
    EventSubscriptionPositionError,
)
from framework.events.runtime.diagnostics import DeliveryDiagnosticProjector
from framework.events.runtime.fallback import (
    LocalRuntimeDiagnosticFallback,
    RuntimeDiagnosticCategory,
    RuntimeDiagnosticComponent,
    RuntimeDiagnosticOperation,
)
from framework.events.runtime.idempotency import (
    AutomaticDeliveryOperation,
    IdempotencyCapabilityRegistry,
    effect_idempotency_key,
)
from framework.events.runtime.inbox import (
    InboxTransactionalEffectRunner,
    InboxTransactionResult,
    validate_inbox_transaction_capability,
)
from framework.events.runtime.models import (
    ClaimedDelivery,
    DeadLetterAction,
    DeadLetterRecord,
    DeliveryClaimRequest,
    DeliveryRecord,
    DeliverySettlement,
    DeliverySettlementResult,
    DeliveryState,
    DurableSubscription,
    EffectIdempotencyStrategy,
    SubscriptionKey,
    SubscriptionStatus,
)
from framework.events.subscriber import (
    ConsumerDeliveryContext,
    ConsumerDisposition,
    ConsumerErrorClassifier,
    ConsumerFailure,
    ConsumerFailureKind,
    ConsumerOutcome,
    DefaultConsumerErrorClassifier,
    DropAuthorizationPolicy,
    DurableEventConsumer,
    MAX_CONSUMER_REASON_CLASS_LENGTH,
    StaticDropAuthorizationPolicy,
    failure_from_outcome,
)
from framework.events.runtime.retry import RetryPlanner

if TYPE_CHECKING:
    from framework.events.ports import EventStorePort


Clock = Callable[[], datetime]
_MAX_SAFE_DIAGNOSTIC_LENGTH: Final = 256
_T = TypeVar("_T")


class EventDeliveryConfigurationError(EventDeliveryError):
    """Raised when durable delivery has no usable framework-owned dependency."""


class EventSubscriptionNotFoundError(EventDeliveryError, LookupError):
    """Raised when a requested durable subscription version does not exist."""

    def __init__(self, key: SubscriptionKey) -> None:
        self.subscription_key = key
        super().__init__(
            "durable event subscription is not registered: "
            f"{key.subscription_id}@{key.subscription_version}"
        )


class EventConsumerNotRegisteredError(EventDeliveryError, LookupError):
    """Raised when a durable subscription has no process-local consumer binding."""

    def __init__(self, key: SubscriptionKey) -> None:
        self.subscription_key = key
        super().__init__(
            "durable event consumer is not attached: "
            f"{key.subscription_id}@{key.subscription_version}"
        )


class EventConsumerMismatchError(EventDeliveryError):
    """Raised when persisted, claimed, and process-local consumer identities differ."""


class EventDeliveryContractError(EventDeliveryError):
    """Raised when a store or consumer violates the durable delivery contract."""


class EventDeliveryStoreOperationError(EventDeliveryError):
    """Safe wrapper for an unexpected concrete-store delivery failure."""


class EventDeadLetterNotFoundError(EventDeliveryError, LookupError):
    """Raised when a requested dead letter does not exist in subscription scope."""


class DeliveryFailurePhase(str, Enum):
    CLAIM_VALIDATION = "claim_validation"
    IDEMPOTENCY = "idempotency"
    INBOX_READ = "inbox_read"
    CONSUMER = "consumer"
    CLOCK = "clock"
    SETTLEMENT = "settlement"


@dataclass(frozen=True, slots=True)
class DeliveryProcessingFailure:
    """Bounded diagnostic that never retains an exception object or its message."""

    phase: DeliveryFailurePhase
    reason_class: str
    redacted_diagnostic: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "phase", DeliveryFailurePhase(self.phase))
        reason_class = _required_text(self.reason_class, "reason_class")
        if len(reason_class) > MAX_CONSUMER_REASON_CLASS_LENGTH:
            raise ValueError(
                "reason_class exceeds the "
                f"{MAX_CONSUMER_REASON_CLASS_LENGTH} character limit"
            )
        object.__setattr__(self, "reason_class", reason_class)
        diagnostic = _required_text(
            self.redacted_diagnostic,
            "redacted_diagnostic",
        )
        object.__setattr__(
            self,
            "redacted_diagnostic",
            diagnostic[:_MAX_SAFE_DIAGNOSTIC_LENGTH],
        )


@dataclass(frozen=True, slots=True)
class DeliveryAttemptResult:
    delivery_id: str
    event_id: str
    stream_id: str
    stream_sequence: int
    subscription_id: str
    subscription_version: int
    delivery_generation: int
    attempt_count: int
    state: DeliveryState | None
    consumer_called: bool
    inbox_already_completed: bool
    settlement: DeliverySettlementResult | None = None
    failure: DeliveryProcessingFailure | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "delivery_id",
            "event_id",
            "stream_id",
            "subscription_id",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )
        for field_name in (
            "stream_sequence",
            "subscription_version",
            "delivery_generation",
            "attempt_count",
        ):
            _positive_int(getattr(self, field_name), field_name)
        if self.state is not None:
            object.__setattr__(self, "state", DeliveryState(self.state))
        for field_name in ("consumer_called", "inbox_already_completed"):
            if not isinstance(getattr(self, field_name), bool):
                raise TypeError(f"{field_name} must be a boolean")
        if self.settlement is not None and not isinstance(
            self.settlement,
            DeliverySettlementResult,
        ):
            raise TypeError("settlement must be DeliverySettlementResult")
        if self.failure is not None and not isinstance(
            self.failure,
            DeliveryProcessingFailure,
        ):
            raise TypeError("failure must be DeliveryProcessingFailure")
        if (self.settlement is None) == (self.failure is None):
            raise ValueError("delivery result requires exactly one settlement or failure")
        if self.settlement is not None:
            settled = self.settlement.delivery
            if (
                settled.delivery_id != self.delivery_id
                or settled.event_id != self.event_id
                or settled.stream_id != self.stream_id
                or settled.stream_sequence != self.stream_sequence
                or settled.subscription_id != self.subscription_id
                or settled.subscription_version != self.subscription_version
                or settled.delivery_generation != self.delivery_generation
                or settled.attempt_count != self.attempt_count
            ):
                raise ValueError("settlement identity does not match result")
            if self.state is not settled.state:
                raise ValueError("settlement state does not match result")
        elif self.state is not None:
            raise ValueError("failed delivery processing cannot assert a durable state")
        if self.inbox_already_completed and self.consumer_called:
            raise ValueError("an inbox-deduplicated delivery cannot call the consumer")


@dataclass(frozen=True, slots=True)
class DeliveryBatchResult:
    subscription_id: str
    subscription_version: int
    lease_owner: str
    requested_limit: int
    requested_at: datetime
    completed_at: datetime
    attempts: tuple[DeliveryAttemptResult, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "subscription_id",
            _required_text(self.subscription_id, "subscription_id"),
        )
        _positive_int(self.subscription_version, "subscription_version")
        object.__setattr__(
            self,
            "lease_owner",
            _required_text(self.lease_owner, "lease_owner"),
        )
        _positive_int(self.requested_limit, "requested_limit")
        requested_at = _utc(self.requested_at, "requested_at")
        completed_at = _utc(self.completed_at, "completed_at")
        if completed_at < requested_at:
            raise ValueError("completed_at cannot precede requested_at")
        object.__setattr__(self, "requested_at", requested_at)
        object.__setattr__(self, "completed_at", completed_at)
        attempts = tuple(self.attempts)
        if any(not isinstance(item, DeliveryAttemptResult) for item in attempts):
            raise TypeError("attempts must contain DeliveryAttemptResult values")
        if len(attempts) > self.requested_limit:
            raise ValueError("attempt count exceeds the bounded claim limit")
        if any(
            item.subscription_id != self.subscription_id
            or item.subscription_version != self.subscription_version
            for item in attempts
        ):
            raise ValueError("attempt subscription does not match batch result")
        object.__setattr__(self, "attempts", attempts)

    @property
    def claimed_count(self) -> int:
        return len(self.attempts)

    @property
    def acknowledged_count(self) -> int:
        return sum(item.state is DeliveryState.ACKED for item in self.attempts)

    @property
    def retry_scheduled_count(self) -> int:
        return sum(item.state is DeliveryState.RETRY_WAIT for item in self.attempts)

    @property
    def dropped_count(self) -> int:
        return sum(item.state is DeliveryState.DROPPED for item in self.attempts)

    @property
    def dead_lettered_count(self) -> int:
        return sum(item.state is DeliveryState.DEAD_LETTER for item in self.attempts)

    @property
    def inbox_deduplicated_count(self) -> int:
        return sum(item.inbox_already_completed for item in self.attempts)

    @property
    def processing_failure_count(self) -> int:
        return sum(item.failure is not None for item in self.attempts)


@dataclass(frozen=True, slots=True)
class _ConsumerBinding:
    consumer: DurableEventConsumer
    consumer_id: str
    subscription_fingerprint: str


class DurableConsumerRegistry:
    """Process-local consumer bindings backed by durable subscription versions."""

    def __init__(
        self,
        store: EventStorePort | None,
        *,
        idempotency_capabilities: IdempotencyCapabilityRegistry | None = None,
        inbox_transaction_runner: InboxTransactionalEffectRunner | None = None,
        diagnostic_fallback: LocalRuntimeDiagnosticFallback | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._store = store
        self._idempotency_capabilities = idempotency_capabilities
        self._inbox_transaction_runner = inbox_transaction_runner
        self._diagnostic_fallback = (
            diagnostic_fallback
            if diagnostic_fallback is not None
            else LocalRuntimeDiagnosticFallback()
        )
        self._clock = clock or _system_clock
        self._bindings: dict[SubscriptionKey, _ConsumerBinding] = {}
        self._lock = RLock()

    @property
    def store(self) -> EventStorePort | None:
        return self._store

    @property
    def inbox_transaction_runner(self) -> InboxTransactionalEffectRunner | None:
        return self._inbox_transaction_runner

    @property
    def diagnostic_fallback(self) -> LocalRuntimeDiagnosticFallback:
        return self._diagnostic_fallback

    @property
    def registered_keys(self) -> tuple[SubscriptionKey, ...]:
        with self._lock:
            return tuple(
                sorted(
                    self._bindings,
                    key=lambda item: (
                        item.subscription_id,
                        item.subscription_version,
                    ),
                )
            )

    def register(
        self,
        subscription: DurableSubscription,
        consumer: DurableEventConsumer,
    ) -> DurableSubscription:
        """Validate the binding/capability before durable version registration."""

        if not isinstance(subscription, DurableSubscription):
            raise TypeError("subscription must be DurableSubscription")
        consumer_id = _validate_consumer(consumer)
        if consumer_id != subscription.consumer_id:
            raise EventConsumerMismatchError(
                "consumer_id does not match durable subscription"
            )
        store = self._require_store()
        self._validate_activation(subscription)

        persisted = _register_subscription_safely(
            store,
            subscription,
            diagnostic_fallback=self._diagnostic_fallback,
        )
        self._assert_subscription_matches(subscription, persisted)
        binding = _ConsumerBinding(
            consumer=consumer,
            consumer_id=consumer_id,
            subscription_fingerprint=_subscription_fingerprint(persisted),
        )
        with self._lock:
            current = self._bindings.get(persisted.key)
            if current is not None and current.consumer is not consumer:
                raise EventConsumerMismatchError(
                    "subscription version is already attached to another consumer instance"
                )
            self._bindings[persisted.key] = binding
        return persisted

    def attach(
        self,
        key: SubscriptionKey,
        consumer: DurableEventConsumer,
    ) -> DurableSubscription:
        """Attach a worker after restart without creating a missing subscription."""

        subscription = self._get_subscription(key)
        consumer_id = _validate_consumer(consumer)
        if consumer_id != subscription.consumer_id:
            raise EventConsumerMismatchError(
                "consumer_id does not match durable subscription"
            )
        self._validate_activation(subscription)
        binding = _ConsumerBinding(
            consumer=consumer,
            consumer_id=consumer_id,
            subscription_fingerprint=_subscription_fingerprint(subscription),
        )
        with self._lock:
            current = self._bindings.get(key)
            if current is not None and current.consumer is not consumer:
                raise EventConsumerMismatchError(
                    "subscription version is already attached to another consumer instance"
                )
            self._bindings[key] = binding
        return subscription

    def resolve(
        self,
        key: SubscriptionKey,
    ) -> tuple[DurableSubscription, DurableEventConsumer]:
        subscription = self._get_subscription(key)
        with self._lock:
            binding = self._bindings.get(key)
        if binding is None:
            raise EventConsumerNotRegisteredError(key)
        current_consumer_id = _validate_consumer(binding.consumer)
        if (
            binding.consumer_id != current_consumer_id
            or current_consumer_id != subscription.consumer_id
            or binding.subscription_fingerprint
            != _subscription_fingerprint(subscription)
        ):
            raise EventConsumerMismatchError(
                "durable subscription and consumer binding no longer match"
            )
        return subscription, binding.consumer

    def require_operation(
        self,
        subscription: DurableSubscription,
        operation: AutomaticDeliveryOperation,
    ) -> None:
        operation = AutomaticDeliveryOperation(operation)
        if (
            operation is AutomaticDeliveryOperation.REQUEUE
            and not subscription.supports_out_of_order_repair
        ):
            raise EventConsumerIdempotencyError(
                "subscription does not support idempotent out-of-order repair"
            )
        if not subscription.effect.performs_external_effects:
            return
        capabilities = self._idempotency_capabilities
        if capabilities is None:
            raise EventConsumerIdempotencyError(
                "external-effect subscription has no idempotency capability registry"
            )
        capability_failed = False
        try:
            capabilities.require_for_delivery(subscription, operation)
        except Exception:
            capability_failed = True
        if capability_failed:
            raise EventConsumerIdempotencyError(
                "external-effect idempotency capability is unavailable"
            )
        self._validate_inbox_transaction_runner(subscription)

    def set_status(
        self,
        key: SubscriptionKey,
        status: SubscriptionStatus,
        *,
        reason: str,
    ) -> DurableSubscription:
        normalized_status = SubscriptionStatus(status)
        if normalized_status is SubscriptionStatus.ACTIVE:
            subscription, _consumer = self.resolve(key)
            # Resume is an activation boundary.  A capability validated before a
            # long pause may have been revoked or may no longer describe the
            # composed target, so it must be proven again before claims resume.
            self._validate_activation(subscription)
        else:
            # Emergency pause/retirement remains operable when the worker process
            # is down or its consumer implementation is deliberately unloaded.
            subscription = self._get_subscription(key)
        changed_at = _clock_value(self._clock)
        persisted = self._store_call(
            RuntimeDiagnosticOperation.SUBSCRIPTION_STATUS_UPDATE,
            "subscription status update",
            lambda: self._require_store().set_subscription_status(
                key,
                normalized_status,
                changed_at=changed_at,
                reason=_required_text(reason, "reason"),
            ),
        )
        invalid_response: EventDeliveryContractError | None = None
        if not isinstance(persisted, DurableSubscription):
            invalid_response = EventDeliveryContractError(
                "durable store returned an invalid subscription value"
            )
        elif (
            persisted.key != key
            or persisted.status is not normalized_status
            or _subscription_fingerprint(persisted)
            != _subscription_fingerprint(subscription)
        ):
            invalid_response = EventDeliveryContractError(
                "durable store returned an invalid subscription status update"
            )
        if invalid_response is not None:
            self._record_store_failure(
                RuntimeDiagnosticOperation.SUBSCRIPTION_STATUS_UPDATE,
                invalid_response,
            )
            raise invalid_response
        return persisted

    def pause(self, key: SubscriptionKey, *, reason: str) -> DurableSubscription:
        return self.set_status(key, SubscriptionStatus.PAUSED, reason=reason)

    def resume(self, key: SubscriptionKey, *, reason: str) -> DurableSubscription:
        return self.set_status(key, SubscriptionStatus.ACTIVE, reason=reason)

    def retire(self, key: SubscriptionKey, *, reason: str) -> DurableSubscription:
        return self.set_status(key, SubscriptionStatus.RETIRED, reason=reason)

    def _get_subscription(self, key: SubscriptionKey) -> DurableSubscription:
        if not isinstance(key, SubscriptionKey):
            raise TypeError("key must be SubscriptionKey")
        subscription = self._store_call(
            RuntimeDiagnosticOperation.SUBSCRIPTION_LOOKUP,
            "subscription lookup",
            lambda: self._require_store().get_subscription(key),
        )
        if subscription is None:
            raise EventSubscriptionNotFoundError(key)
        if not isinstance(subscription, DurableSubscription):
            failure = EventDeliveryContractError(
                "durable store returned an invalid subscription value"
            )
            self._record_store_failure(
                RuntimeDiagnosticOperation.SUBSCRIPTION_LOOKUP,
                failure,
            )
            raise failure
        if subscription.key != key:
            failure = EventDeliveryContractError(
                "durable store returned a different subscription version"
            )
            self._record_store_failure(
                RuntimeDiagnosticOperation.SUBSCRIPTION_LOOKUP,
                failure,
            )
            raise failure
        return subscription

    def _validate_activation(self, subscription: DurableSubscription) -> None:
        if not subscription.effect.performs_external_effects:
            return
        capabilities = self._idempotency_capabilities
        if capabilities is None:
            raise EventConsumerIdempotencyError(
                "external-effect subscription has no idempotency capability registry"
            )
        activation_failed = False
        try:
            capabilities.validate_for_activation(subscription)
        except Exception:
            activation_failed = True
        if activation_failed:
            raise EventConsumerIdempotencyError(
                "external-effect subscription failed idempotency activation"
            )
        self._validate_inbox_transaction_runner(subscription)

    def _validate_inbox_transaction_runner(
        self,
        subscription: DurableSubscription,
    ) -> None:
        if (
            subscription.effect.idempotency_strategy
            is not EffectIdempotencyStrategy.INBOX_TRANSACTION
        ):
            return
        runner_failed = False
        try:
            validate_inbox_transaction_capability(
                subscription,
                self._inbox_transaction_runner,
            )
        except Exception:
            runner_failed = True
        if runner_failed:
            raise EventConsumerIdempotencyError(
                "INBOX_TRANSACTION has no matching transactional effect runner"
            )

    def _assert_subscription_matches(
        self,
        requested: DurableSubscription,
        persisted: DurableSubscription,
    ) -> None:
        if not isinstance(persisted, DurableSubscription):
            failure = EventDeliveryContractError(
                "durable store returned an invalid subscription value"
            )
            self._record_store_failure(
                RuntimeDiagnosticOperation.SUBSCRIPTION_REGISTRATION,
                failure,
            )
            raise failure
        if (
            requested.key != persisted.key
            or requested.consumer_id != persisted.consumer_id
            or _subscription_fingerprint(requested)
            != _subscription_fingerprint(persisted)
        ):
            raise EventConsumerMismatchError(
                "persisted subscription does not match the requested version"
            )

    def _require_store(self) -> EventStorePort:
        if self._store is None:
            raise EventDeliveryConfigurationError(
                "durable delivery requires an event store"
            )
        return self._store

    def _store_call(
        self,
        diagnostic_operation: RuntimeDiagnosticOperation,
        operation: str,
        call: Callable[[], _T],
    ) -> _T:
        failed = False
        try:
            return call()
        except Exception as error:
            self._record_store_failure(diagnostic_operation, error)
            failed = True
        if failed:
            raise EventDeliveryStoreOperationError(
                f"durable event store {operation} failed"
            )
        raise AssertionError("unreachable durable store call state")

    def _record_store_failure(
        self,
        operation: RuntimeDiagnosticOperation,
        error: Exception,
    ) -> None:
        self._diagnostic_fallback.record(
            category=RuntimeDiagnosticCategory.DELIVERY_STORE_FAILURE,
            component=RuntimeDiagnosticComponent.DELIVERY_CONSUMER_REGISTRY,
            operation=operation,
            error=error,
        )


class DurableDeliveryRuntime:
    """Bounded, isolated orchestration over a durable delivery ledger."""

    def __init__(
        self,
        store: EventStorePort | None,
        *,
        consumers: DurableConsumerRegistry | None = None,
        idempotency_capabilities: IdempotencyCapabilityRegistry | None = None,
        inbox_transaction_runner: InboxTransactionalEffectRunner | None = None,
        retry_planner: RetryPlanner | None = None,
        error_classifier: ConsumerErrorClassifier | None = None,
        drop_policy: DropAuthorizationPolicy | None = None,
        diagnostic_projector: DeliveryDiagnosticProjector | None = None,
        diagnostic_fallback: LocalRuntimeDiagnosticFallback | None = None,
        clock: Clock | None = None,
    ) -> None:
        if consumers is not None and (
            idempotency_capabilities is not None
            or inbox_transaction_runner is not None
        ):
            raise EventDeliveryConfigurationError(
                "idempotency capabilities and inbox runner belong to the supplied "
                "consumer registry"
            )
        if (
            consumers is not None
            and store is not None
            and consumers.store is not store
        ):
            raise EventDeliveryConfigurationError(
                "delivery runtime and consumer registry must share one event store"
            )
        if (
            consumers is not None
            and diagnostic_fallback is not None
            and consumers.diagnostic_fallback is not diagnostic_fallback
        ):
            raise EventDeliveryConfigurationError(
                "delivery runtime and consumer registry must share one "
                "diagnostic fallback"
            )
        self._store = store
        self._clock = clock or _system_clock
        self._diagnostic_fallback = (
            diagnostic_fallback
            if diagnostic_fallback is not None
            else (
                consumers.diagnostic_fallback
                if consumers is not None
                else LocalRuntimeDiagnosticFallback()
            )
        )
        self._consumers = consumers or DurableConsumerRegistry(
            store,
            idempotency_capabilities=idempotency_capabilities,
            inbox_transaction_runner=inbox_transaction_runner,
            diagnostic_fallback=self._diagnostic_fallback,
            clock=self._clock,
        )
        self._inbox_transaction_runner = self._consumers.inbox_transaction_runner
        self._retry_planner = retry_planner or RetryPlanner()
        self._error_classifier = error_classifier or DefaultConsumerErrorClassifier()
        self._drop_policy = drop_policy or StaticDropAuthorizationPolicy()
        self._diagnostic_projector = (
            diagnostic_projector or DeliveryDiagnosticProjector()
        )

    @property
    def consumers(self) -> DurableConsumerRegistry:
        return self._consumers

    @property
    def diagnostic_fallback(self) -> LocalRuntimeDiagnosticFallback:
        return self._diagnostic_fallback

    def register(
        self,
        subscription: DurableSubscription,
        consumer: DurableEventConsumer,
    ) -> DurableSubscription:
        return self._consumers.register(subscription, consumer)

    def dispatch_batch(
        self,
        key: SubscriptionKey,
        *,
        lease_owner: str,
        limit: int | None = None,
        stream_id: str | None = None,
    ) -> DeliveryBatchResult:
        store = self._require_store()
        subscription, consumer = self._consumers.resolve(key)
        requested_at = _clock_value(self._clock)
        requested_limit = _bounded_claim_limit(subscription, limit)
        normalized_lease_owner = _required_text(lease_owner, "lease_owner")
        if subscription.status is SubscriptionStatus.PAUSED:
            return DeliveryBatchResult(
                subscription_id=subscription.subscription_id,
                subscription_version=subscription.subscription_version,
                lease_owner=normalized_lease_owner,
                requested_limit=requested_limit,
                requested_at=requested_at,
                completed_at=_clock_value_or_floor(self._clock, requested_at),
                attempts=(),
            )
        # The concrete capability registry proves the entire automatic-delivery
        # operation set here before the store changes a pending row to CLAIMED.
        # Each returned claim is checked again using its actual generation and
        # attempt because callers must not label a claim as recovery/redelivery.
        self._consumers.require_operation(
            subscription,
            AutomaticDeliveryOperation.INITIAL_DELIVERY,
        )
        request = DeliveryClaimRequest(
            subscription_id=subscription.subscription_id,
            subscription_version=subscription.subscription_version,
            lease_owner=normalized_lease_owner,
            requested_at=requested_at,
            lease_duration_seconds=subscription.lease_policy.duration_seconds,
            limit=requested_limit,
            stream_id=stream_id,
        )
        claim_response = self._store_call(
            RuntimeDiagnosticOperation.DELIVERY_CLAIM,
            "delivery claim",
            lambda: store.claim_deliveries(request),
        )
        try:
            claimed = tuple(claim_response)
        except Exception as error:
            self._record_store_failure(
                RuntimeDiagnosticOperation.DELIVERY_CLAIM,
                error,
            )
            raise
        if len(claimed) > requested_limit:
            failure = EventDeliveryContractError(
                "durable store exceeded the bounded delivery claim limit"
            )
            self._record_store_failure(
                RuntimeDiagnosticOperation.DELIVERY_CLAIM,
                failure,
            )
            raise failure
        if any(not isinstance(item, ClaimedDelivery) for item in claimed):
            failure = EventDeliveryContractError(
                "durable store returned an invalid claimed delivery"
            )
            self._record_store_failure(
                RuntimeDiagnosticOperation.DELIVERY_CLAIM,
                failure,
            )
            raise failure
        duplicate_delivery_ids = _duplicate_delivery_ids(claimed)
        if duplicate_delivery_ids:
            self._record_store_failure(
                RuntimeDiagnosticOperation.DELIVERY_CLAIM,
                EventDeliveryContractError(
                    "durable store returned a duplicate delivery claim"
                ),
            )
        attempts = tuple(
            (
                _failed_attempt(
                    item,
                    phase=DeliveryFailurePhase.CLAIM_VALIDATION,
                    reason_class="duplicate_delivery_claim",
                    error=EventDeliveryContractError(
                        "durable store returned a duplicate delivery claim"
                    ),
                )
                if item.delivery.delivery_id in duplicate_delivery_ids
                else self._process_claim(
                    subscription=subscription,
                    consumer=consumer,
                    claimed=item,
                    expected_lease_owner=request.lease_owner,
                    requested_at=requested_at,
                )
            )
            for item in claimed
        )
        return DeliveryBatchResult(
            subscription_id=subscription.subscription_id,
            subscription_version=subscription.subscription_version,
            lease_owner=request.lease_owner,
            requested_limit=requested_limit,
            requested_at=requested_at,
            completed_at=_clock_value_or_floor(self._clock, requested_at),
            attempts=attempts,
        )

    def requeue_dead_letter(
        self,
        key: SubscriptionKey,
        action: DeadLetterAction,
    ) -> DeliveryRecord:
        if not isinstance(action, DeadLetterAction):
            raise TypeError("action must be DeadLetterAction")
        subscription, _consumer = self._consumers.resolve(key)
        if not action.idempotency_ready:
            raise EventConsumerIdempotencyError(
                "dead-letter requeue requires an idempotency-ready consumer"
            )
        self._consumers.require_operation(
            subscription,
            AutomaticDeliveryOperation.REQUEUE,
        )
        store = self._require_store()
        record = self._store_call(
            RuntimeDiagnosticOperation.DEAD_LETTER_LOOKUP,
            "dead-letter lookup",
            lambda: store.get_dead_letter(
                action.dead_letter_id,
                tenant_id=subscription.tenant_id,
            ),
        )
        if record is None:
            raise EventDeadLetterNotFoundError(
                "dead letter is not available in subscription scope"
            )
        if not isinstance(record, DeadLetterRecord):
            failure = EventDeliveryContractError(
                "durable store returned an invalid dead-letter value"
            )
            self._record_store_failure(
                RuntimeDiagnosticOperation.DEAD_LETTER_LOOKUP,
                failure,
            )
            raise failure
        if (
            record.subscription_id != subscription.subscription_id
            or record.subscription_version != subscription.subscription_version
            or record.consumer_id != subscription.consumer_id
            or record.consumer_effect_id != subscription.effect.consumer_effect_id
            or record.tenant_id != subscription.tenant_id
        ):
            raise EventConsumerMismatchError(
                "dead letter does not belong to the selected subscription"
            )
        delivery = self._store_call(
            RuntimeDiagnosticOperation.DEAD_LETTER_REQUEUE,
            "dead-letter requeue",
            lambda: store.requeue_dead_letter(action),
        )
        if not isinstance(delivery, DeliveryRecord):
            failure = EventDeliveryContractError(
                "durable store returned an invalid requeue delivery"
            )
            self._record_store_failure(
                RuntimeDiagnosticOperation.DEAD_LETTER_REQUEUE,
                failure,
            )
            raise failure
        if (
            delivery.event_id != record.event_id
            or delivery.subscription_id != record.subscription_id
            or delivery.subscription_version != record.subscription_version
            or delivery.consumer_id != record.consumer_id
            or delivery.delivery_generation <= record.delivery_generation
            or delivery.state is not DeliveryState.PENDING
        ):
            failure = EventDeliveryContractError(
                "durable store returned an invalid requeue delivery"
            )
            self._record_store_failure(
                RuntimeDiagnosticOperation.DEAD_LETTER_REQUEUE,
                failure,
            )
            raise failure
        return delivery

    def _process_claim(
        self,
        *,
        subscription: DurableSubscription,
        consumer: DurableEventConsumer,
        claimed: ClaimedDelivery,
        expected_lease_owner: str,
        requested_at: datetime,
    ) -> DeliveryAttemptResult:
        try:
            self._validate_claim(
                subscription,
                claimed,
                expected_lease_owner=expected_lease_owner,
                requested_at=requested_at,
            )
        except Exception as exc:
            self._record_store_failure(
                RuntimeDiagnosticOperation.DELIVERY_CLAIM,
                exc,
            )
            return _failed_attempt(
                claimed,
                phase=DeliveryFailurePhase.CLAIM_VALIDATION,
                reason_class="invalid_delivery_claim",
                error=exc,
            )

        try:
            for operation in _claim_operations(claimed):
                self._consumers.require_operation(subscription, operation)
        except Exception as exc:
            return _failed_attempt(
                claimed,
                phase=DeliveryFailurePhase.IDEMPOTENCY,
                reason_class="idempotency_capability_unavailable",
                error=exc,
            )

        effect_id = subscription.effect.consumer_effect_id
        idempotency_key = (
            None
            if effect_id is None
            else effect_idempotency_key(claimed.event.event_id, effect_id)
        )
        context = ConsumerDeliveryContext(
            delivery_id=claimed.delivery.delivery_id,
            subscription_id=subscription.subscription_id,
            subscription_version=subscription.subscription_version,
            delivery_generation=claimed.delivery.delivery_generation,
            attempt_count=claimed.delivery.attempt_count,
            consumer_id=subscription.consumer_id,
            consumer_effect_id=effect_id,
            idempotency_key=idempotency_key,
        )
        try:
            settled_at = _clock_value(self._clock)
        except Exception as exc:
            return _failed_attempt(
                claimed,
                phase=DeliveryFailurePhase.CLOCK,
                reason_class="delivery_clock_unavailable",
                error=exc,
            )

        consumer_called = True
        inbox_already_completed = False
        strategy = subscription.effect.idempotency_strategy
        if strategy is EffectIdempotencyStrategy.INBOX_TRANSACTION:
            runner = self._inbox_transaction_runner
            assert runner is not None  # activation and per-claim gates prove this
            try:
                transaction_result = runner.execute(
                    subscription=subscription,
                    consumer=consumer,
                    claimed=claimed,
                    context=context,
                    settled_at=settled_at,
                )
                if not isinstance(transaction_result, InboxTransactionResult):
                    raise EventDeliveryContractError(
                        "transactional effect runner returned an invalid result"
                    )
                consumer_called = transaction_result.consumer_called
                inbox_already_completed = (
                    transaction_result.inbox_already_completed
                )
                if transaction_result.settlement is not None:
                    try:
                        _validate_inbox_transaction_result(
                            claimed,
                            transaction_result,
                            settled_at=settled_at,
                        )
                    except Exception as exc:
                        return _failed_attempt(
                            claimed,
                            phase=DeliveryFailurePhase.SETTLEMENT,
                            reason_class="inbox_transaction_contract_failed",
                            error=exc,
                            consumer_called=consumer_called,
                            inbox_already_completed=inbox_already_completed,
                        )
                    return _settled_attempt(
                        claimed,
                        transaction_result.settlement,
                        consumer_called=consumer_called,
                        inbox_already_completed=inbox_already_completed,
                    )
                outcome = transaction_result.outcome
                assert outcome is not None
                failure = self._failure_from_outcome(
                    outcome,
                    subscription=subscription,
                    claimed=claimed,
                )
            except Exception as exc:
                failure = self._safe_classify(exc)
                outcome = None
        else:
            try:
                outcome = consumer.consume(claimed.event, context)
                if not isinstance(outcome, ConsumerOutcome):
                    failure = self._project_failure(
                        ConsumerFailure(
                            kind=ConsumerFailureKind.PERMANENT,
                            reason_class="invalid_consumer_outcome",
                            redacted_diagnostic=type(outcome).__name__,
                        ),
                        fallback_reason_class="invalid_consumer_outcome",
                    )
                    outcome = None
                else:
                    failure = self._failure_from_outcome(
                        outcome,
                        subscription=subscription,
                        claimed=claimed,
                    )
            except Exception as exc:
                failure = self._safe_classify(exc)
                outcome = None
        if failure is not None:
            try:
                plan = self._retry_planner.plan(
                    failure=failure,
                    attempt_count=claimed.delivery.attempt_count,
                    policy=subscription.retry_policy,
                    failed_at=settled_at,
                    jitter_key=(
                        f"{claimed.delivery.delivery_id}:"
                        f"{claimed.delivery.delivery_generation}"
                    ),
                )
                settlement = plan.settlement(claimed.lease)
            except Exception as exc:
                return _failed_attempt(
                    claimed,
                    phase=DeliveryFailurePhase.CONSUMER,
                    reason_class="consumer_failure_mapping_failed",
                    error=exc,
                    consumer_called=consumer_called,
                )
            return self._settle(
                claimed,
                settlement,
                consumer_called=consumer_called,
                inbox_already_completed=inbox_already_completed,
            )

        assert outcome is not None
        if outcome.disposition is ConsumerDisposition.DROP:
            projected = self._diagnostic_projector.project(
                reason_class=outcome.reason_class or "drop_without_reason",
                redacted_diagnostic=outcome.redacted_diagnostic,
                fallback_reason_class="policy_approved_drop",
            )
            settlement = DeliverySettlement(
                lease=claimed.lease,
                target_state=DeliveryState.DROPPED,
                settled_at=settled_at,
                reason_class=projected.reason_class,
                redacted_diagnostic=projected.redacted_diagnostic,
            )
        else:
            settlement = DeliverySettlement(
                lease=claimed.lease,
                target_state=DeliveryState.ACKED,
                settled_at=settled_at,
            )
        return self._settle(
            claimed,
            settlement,
            consumer_called=consumer_called,
            inbox_already_completed=inbox_already_completed,
        )

    def _settle(
        self,
        claimed: ClaimedDelivery,
        settlement: DeliverySettlement,
        *,
        consumer_called: bool,
        inbox_already_completed: bool,
    ) -> DeliveryAttemptResult:
        try:
            result = self._require_store().settle_delivery(settlement)
            _validate_settlement_result(claimed, settlement, result)
        except Exception as exc:
            self._record_store_failure(
                RuntimeDiagnosticOperation.DELIVERY_SETTLEMENT,
                exc,
            )
            return _failed_attempt(
                claimed,
                phase=DeliveryFailurePhase.SETTLEMENT,
                reason_class="delivery_settlement_failed",
                error=exc,
                consumer_called=consumer_called,
                inbox_already_completed=inbox_already_completed,
            )
        return _settled_attempt(
            claimed,
            result,
            consumer_called=consumer_called,
            inbox_already_completed=inbox_already_completed,
        )

    def _safe_classify(self, error: Exception) -> ConsumerFailure:
        try:
            failure = self._error_classifier.classify(error)
            if not isinstance(failure, ConsumerFailure):
                raise TypeError("classifier returned an invalid failure")
        except Exception as classifier_error:
            failure = DefaultConsumerErrorClassifier().classify(classifier_error)
        return self._project_failure(failure)

    def _failure_from_outcome(
        self,
        outcome: ConsumerOutcome,
        *,
        subscription: DurableSubscription,
        claimed: ClaimedDelivery,
    ) -> ConsumerFailure | None:
        failure = failure_from_outcome(
            outcome,
            subscription=subscription,
            event=claimed.event,
            drop_policy=self._drop_policy,
        )
        if failure is None:
            return None
        if failure.reason_class == "unapproved_drop":
            fallback = "unapproved_drop"
        elif outcome.disposition is ConsumerDisposition.RETRY:
            fallback = "consumer_requested_retry"
        else:
            fallback = None
        return self._project_failure(failure, fallback_reason_class=fallback)

    def _project_failure(
        self,
        failure: ConsumerFailure,
        *,
        fallback_reason_class: str | None = None,
    ) -> ConsumerFailure:
        fallback = fallback_reason_class
        if fallback is None:
            fallback = (
                "permanent_processing_failure"
                if failure.kind is ConsumerFailureKind.PERMANENT
                else "transient_processing_failure"
            )
        return self._diagnostic_projector.project_failure(
            failure,
            fallback_reason_class=fallback,
        )

    def _validate_claim(
        self,
        subscription: DurableSubscription,
        claimed: ClaimedDelivery,
        *,
        expected_lease_owner: str,
        requested_at: datetime,
    ) -> None:
        if not isinstance(claimed, ClaimedDelivery):
            raise EventDeliveryContractError(
                "durable store returned an invalid claimed delivery"
            )
        delivery = claimed.delivery
        if (
            delivery.subscription_id != subscription.subscription_id
            or delivery.subscription_version != subscription.subscription_version
            or delivery.consumer_id != subscription.consumer_id
            or delivery.consumer_effect_id != subscription.effect.consumer_effect_id
            or delivery.tenant_id != subscription.tenant_id
            or claimed.event.tenant_id != subscription.tenant_id
        ):
            raise EventConsumerMismatchError(
                "claimed delivery does not match the durable subscription"
            )
        if (
            claimed.lease.lease_owner != expected_lease_owner
            or claimed.lease.lease_expires_at <= requested_at
        ):
            raise EventDeliveryContractError(
                "claimed delivery has an invalid lease boundary"
            )
        event_filter = subscription.event_filter
        if (
            event_filter.event_types
            and claimed.event.event_type not in event_filter.event_types
        ) or (
            event_filter.data_schemas
            and claimed.event.data_schema not in event_filter.data_schemas
        ):
            raise EventDeliveryContractError(
                "claimed event does not match the durable subscription filter"
            )

    def _require_store(self) -> EventStorePort:
        if self._store is None:
            raise EventDeliveryConfigurationError(
                "durable delivery requires an event store"
            )
        return self._store

    def _store_call(
        self,
        diagnostic_operation: RuntimeDiagnosticOperation,
        operation: str,
        call: Callable[[], _T],
    ) -> _T:
        failed = False
        try:
            return call()
        except Exception as error:
            self._record_store_failure(diagnostic_operation, error)
            failed = True
        if failed:
            raise EventDeliveryStoreOperationError(
                f"durable event store {operation} failed"
            )
        raise AssertionError("unreachable durable store call state")

    def _record_store_failure(
        self,
        operation: RuntimeDiagnosticOperation,
        error: Exception,
    ) -> None:
        self._diagnostic_fallback.record(
            category=RuntimeDiagnosticCategory.DELIVERY_STORE_FAILURE,
            component=RuntimeDiagnosticComponent.DELIVERY_RUNTIME,
            operation=operation,
            error=error,
        )


def _claim_operations(
    claimed: ClaimedDelivery,
) -> tuple[AutomaticDeliveryOperation, ...]:
    operations: list[AutomaticDeliveryOperation] = []
    if claimed.delivery.delivery_generation > 1:
        operations.append(AutomaticDeliveryOperation.REDELIVERY)
    elif claimed.delivery.attempt_count == 1:
        operations.append(AutomaticDeliveryOperation.INITIAL_DELIVERY)
    # The claim DTO intentionally does not trust a worker-supplied prior-state flag.
    # A repeated automatic claim therefore requires proof for both retry and lease
    # recovery before the external effect can be invoked.
    if claimed.delivery.attempt_count > 1:
        operations.extend(
            (
                AutomaticDeliveryOperation.RETRY,
                AutomaticDeliveryOperation.LEASE_RECOVERY,
            )
        )
    return tuple(operations)


def _duplicate_delivery_ids(
    claimed: tuple[ClaimedDelivery, ...],
) -> frozenset[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for item in claimed:
        delivery_id = item.delivery.delivery_id
        if delivery_id in seen:
            duplicates.add(delivery_id)
        seen.add(delivery_id)
    return frozenset(duplicates)


def _bounded_claim_limit(
    subscription: DurableSubscription,
    requested: int | None,
) -> int:
    if requested is None:
        requested = subscription.limits.batch_size
    _positive_int(requested, "limit")
    return min(
        requested,
        subscription.limits.batch_size,
        subscription.limits.max_in_flight,
    )


def _validate_settlement_result(
    claimed: ClaimedDelivery,
    settlement: DeliverySettlement,
    result: DeliverySettlementResult,
) -> None:
    if not isinstance(result, DeliverySettlementResult):
        raise EventDeliveryContractError(
            "durable store returned an invalid settlement result"
        )
    delivery = result.delivery
    if (
        delivery.delivery_id != claimed.delivery.delivery_id
        or delivery.event_id != claimed.event.event_id
        or delivery.stream_id != claimed.delivery.stream_id
        or delivery.stream_sequence != claimed.delivery.stream_sequence
        or delivery.delivery_generation != claimed.delivery.delivery_generation
        or delivery.subscription_id != claimed.delivery.subscription_id
        or delivery.subscription_version != claimed.delivery.subscription_version
        or delivery.consumer_id != claimed.delivery.consumer_id
        or delivery.consumer_effect_id != claimed.delivery.consumer_effect_id
        or delivery.tenant_id != claimed.delivery.tenant_id
        or delivery.attempt_count != claimed.delivery.attempt_count
    ):
        raise EventDeliveryContractError(
            "durable store settled a different delivery identity"
        )
    allowed_states = {settlement.target_state}
    if settlement.target_state is DeliveryState.RETRY_WAIT:
        # Adapters defensively exhaust an over-budget retry to DLQ atomically.
        allowed_states.add(DeliveryState.DEAD_LETTER)
    if delivery.state not in allowed_states:
        raise EventDeliveryContractError(
            "durable store returned an unexpected settlement state"
        )


def _validate_inbox_transaction_result(
    claimed: ClaimedDelivery,
    transaction_result: InboxTransactionResult,
    *,
    settled_at: datetime,
) -> None:
    result = transaction_result.settlement
    if result is None:
        raise EventDeliveryContractError(
            "inbox transaction did not return its ACK settlement"
        )
    expected = DeliverySettlement(
        lease=claimed.lease,
        target_state=DeliveryState.ACKED,
        settled_at=settled_at,
    )
    _validate_settlement_result(claimed, expected, result)
    if not (result.inbox_recorded or transaction_result.inbox_already_completed):
        raise EventDeliveryContractError(
            "inbox transaction ACK has no durable effect-inbox disposition"
        )
    if (
        result.delivery.redacted_diagnostic is not None
        or result.delivery.reason_class
        not in {None, "effect_completed", "effect_already_completed"}
    ):
        raise EventDeliveryContractError(
            "inbox transaction ACK contains an unsafe diagnostic"
        )


def _settled_attempt(
    claimed: ClaimedDelivery,
    result: DeliverySettlementResult,
    *,
    consumer_called: bool,
    inbox_already_completed: bool,
) -> DeliveryAttemptResult:
    delivery = claimed.delivery
    return DeliveryAttemptResult(
        delivery_id=delivery.delivery_id,
        event_id=delivery.event_id,
        stream_id=delivery.stream_id,
        stream_sequence=delivery.stream_sequence,
        subscription_id=delivery.subscription_id,
        subscription_version=delivery.subscription_version,
        delivery_generation=delivery.delivery_generation,
        attempt_count=delivery.attempt_count,
        state=result.delivery.state,
        consumer_called=consumer_called,
        inbox_already_completed=inbox_already_completed,
        settlement=result,
    )


def _failed_attempt(
    claimed: object,
    *,
    phase: DeliveryFailurePhase,
    reason_class: str,
    error: Exception,
    consumer_called: bool = False,
    inbox_already_completed: bool = False,
) -> DeliveryAttemptResult:
    if not isinstance(claimed, ClaimedDelivery):
        # The store has already violated the port, so there is no trustworthy event
        # identity to place in a result DTO.  Escalate without retaining raw data.
        raise EventDeliveryContractError(
            "durable store returned an invalid claimed delivery"
        ) from None
    delivery = claimed.delivery
    return DeliveryAttemptResult(
        delivery_id=delivery.delivery_id,
        event_id=delivery.event_id,
        stream_id=delivery.stream_id,
        stream_sequence=delivery.stream_sequence,
        subscription_id=delivery.subscription_id,
        subscription_version=delivery.subscription_version,
        delivery_generation=delivery.delivery_generation,
        attempt_count=delivery.attempt_count,
        state=None,
        consumer_called=consumer_called,
        inbox_already_completed=inbox_already_completed,
        failure=DeliveryProcessingFailure(
            phase=phase,
            reason_class=reason_class,
            redacted_diagnostic=type(error).__name__,
        ),
    )


def _subscription_fingerprint(subscription: DurableSubscription) -> str:
    from framework.events.canonical import checksum_for

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
            "performs_external_effects": (
                subscription.effect.performs_external_effects
            ),
            "consumer_effect_id": subscription.effect.consumer_effect_id,
            "idempotency_strategy": (
                subscription.effect.idempotency_strategy.value
                if subscription.effect.idempotency_strategy is not None
                else None
            ),
            "retry_policy": {
                "max_attempts": subscription.retry_policy.max_attempts,
                "initial_delay_seconds": (
                    subscription.retry_policy.initial_delay_seconds
                ),
                "multiplier": subscription.retry_policy.multiplier,
                "max_delay_seconds": subscription.retry_policy.max_delay_seconds,
                "jitter_ratio": subscription.retry_policy.jitter_ratio,
            },
            "lease_duration_seconds": subscription.lease_policy.duration_seconds,
            "limits": {
                "batch_size": subscription.limits.batch_size,
                "max_in_flight": subscription.limits.max_in_flight,
                "max_concurrency": subscription.limits.max_concurrency,
                "pending_warning_threshold": (
                    subscription.limits.pending_warning_threshold
                ),
                "pending_hard_limit": subscription.limits.pending_hard_limit,
            },
            "supports_out_of_order_repair": (
                subscription.supports_out_of_order_repair
            ),
        }
    )


def _register_subscription_safely(
    store: EventStorePort,
    subscription: DurableSubscription,
    *,
    diagnostic_fallback: LocalRuntimeDiagnosticFallback,
) -> DurableSubscription:
    position: tuple[str, int, str, int, int] | None = None
    failed = False
    try:
        return store.register_subscription(subscription)
    except EventSubscriptionPositionError as error:
        position = (
            error.subscription_id,
            error.subscription_version,
            error.stream_id,
            error.requested_sequence,
            error.maximum_sequence,
        )
    except Exception as error:
        diagnostic_fallback.record(
            category=RuntimeDiagnosticCategory.DELIVERY_STORE_FAILURE,
            component=RuntimeDiagnosticComponent.DELIVERY_CONSUMER_REGISTRY,
            operation=RuntimeDiagnosticOperation.SUBSCRIPTION_REGISTRATION,
            error=error,
        )
        failed = True
    if position is not None:
        raise EventSubscriptionPositionError(
            subscription_id=position[0],
            subscription_version=position[1],
            stream_id=position[2],
            requested_sequence=position[3],
            maximum_sequence=position[4],
        )
    if failed:
        raise EventDeliveryStoreOperationError(
            "durable subscription registration failed"
        )
    raise AssertionError("unreachable subscription registration state")

def _validate_consumer(consumer: object) -> str:
    validation_failed = False
    try:
        consumer_id = _required_text(getattr(consumer, "consumer_id"), "consumer_id")
        consume = getattr(consumer, "consume")
    except Exception:
        validation_failed = True
        consumer_id = ""
        consume = None
    if validation_failed:
        raise EventConsumerMismatchError(
            "durable consumer must expose a stable consumer_id and consume method"
        )
    if not callable(consume):
        raise EventConsumerMismatchError(
            "durable consumer consume attribute must be callable"
        )
    return consumer_id


def _clock_value(clock: Clock) -> datetime:
    clock_failed = False
    try:
        value = clock()
    except Exception:
        clock_failed = True
        value = None
    if clock_failed:
        raise EventDeliveryConfigurationError("delivery clock failed")
    normalization_failed = False
    try:
        return _utc(value, "clock value")
    except (TypeError, ValueError):
        normalization_failed = True
    if normalization_failed:
        raise EventDeliveryConfigurationError(
            "delivery clock must return a timezone-aware datetime"
        )
    raise AssertionError("unreachable clock normalization state")


def _clock_value_or_floor(clock: Clock, floor: datetime) -> datetime:
    try:
        value = _clock_value(clock)
    except EventDeliveryConfigurationError:
        return floor
    return max(value, floor)


def _system_clock() -> datetime:
    return datetime.now(UTC)


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


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


__all__ = [
    "Clock",
    "DeliveryAttemptResult",
    "DeliveryBatchResult",
    "DeliveryFailurePhase",
    "DeliveryProcessingFailure",
    "DurableConsumerRegistry",
    "DurableDeliveryRuntime",
    "EventConsumerMismatchError",
    "EventConsumerNotRegisteredError",
    "EventDeadLetterNotFoundError",
    "EventDeliveryConfigurationError",
    "EventDeliveryContractError",
    "EventDeliveryStoreOperationError",
    "EventSubscriptionNotFoundError",
]
