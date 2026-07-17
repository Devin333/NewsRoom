from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import traceback
from typing import Any

import pytest

from framework.events.canonical import (
    BusinessContext,
    EventCandidate,
    ProducerIdentity,
    StoredEvent,
    TraceBlock,
)
from framework.events.propagation import W3CSpanContext, current_trace_context
from framework.events.errors import EventConsumerIdempotencyError
from framework.events.runtime.authorization import (
    RedeliveryAuthorizationDecision,
    RedeliveryAuthorizationRequest,
)
from framework.events.runtime.delivery import (
    DeliveryFailurePhase,
    DurableConsumerRegistry,
    DurableDeliveryRuntime,
    EventConsumerMismatchError,
    EventConsumerNotRegisteredError,
    EventDeliveryConfigurationError,
    EventDeliveryStoreOperationError,
    EventRedeliveryAuthorizationContractError,
    EventRedeliveryAuthorizationError,
    EventSubscriptionNotFoundError,
)
from framework.events.runtime.idempotency import (
    AutomaticDeliveryOperation,
    effect_idempotency_key,
    subscription_definition_fingerprint,
)
from framework.events.runtime.fallback import (
    LocalRuntimeDiagnosticFallback,
    RuntimeDiagnosticCategory,
    RuntimeDiagnosticOperation,
)
from framework.events.runtime.inbox import (
    InboxTransactionCapability,
    InboxTransactionResult,
)
from framework.events.runtime.models import (
    ClaimedDelivery,
    ConsumerEffectContract,
    DeadLetterAction,
    DeadLetterDisposition,
    DeadLetterRecord,
    DeliveryClaimRequest,
    DeliveryLeaseToken,
    DeliveryLimits,
    DeliveryRecord,
    DeliverySettlement,
    DeliverySettlementResult,
    DeliveryState,
    DurableSubscription,
    EffectIdempotencyStrategy,
    InboxEntry,
    InboxKey,
    MAX_REDELIVERY_ITEMS,
    PendingDeliveryStats,
    RedeliveryItem,
    RedeliveryReport,
    RedeliveryRequest,
    RetryPolicy,
    SubscriptionFilter,
    SubscriptionKey,
    SubscriptionStart,
    SubscriptionStartPolicy,
    SubscriptionStatus,
)
from framework.events.telemetry import EventTelemetry
from framework.events.subscriber import (
    ConsumerDeliveryContext,
    ConsumerDisposition,
    ConsumerFailure,
    ConsumerFailureKind,
    ConsumerErrorClassifier,
    ConsumerOutcome,
    DropAuthorizationRule,
    PermanentEventProcessingError,
    StaticDropAuthorizationPolicy,
    TransientEventProcessingError,
)


NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)


class _Clock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class _SequenceClock:
    def __init__(self, values: list[datetime | BaseException]) -> None:
        self.values = values

    def __call__(self) -> datetime:
        value = self.values.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


class _CapabilityGate:
    def __init__(self, trace: list[str] | None = None) -> None:
        self.trace = trace if trace is not None else []
        self.validated: list[SubscriptionKey] = []
        self.required: list[AutomaticDeliveryOperation] = []
        self.fail_activation = False
        self.fail_operations: set[AutomaticDeliveryOperation] = set()

    def validate_for_activation(self, subscription: DurableSubscription) -> object:
        self.trace.append("capability")
        self.validated.append(subscription.key)
        if self.fail_activation:
            raise EventConsumerIdempotencyError("capability unavailable")
        return object()

    def require_for_delivery(
        self,
        subscription: DurableSubscription,
        operation: AutomaticDeliveryOperation,
    ) -> object:
        operation = AutomaticDeliveryOperation(operation)
        self.trace.append("capability")
        self.required.append(operation)
        if operation in self.fail_operations:
            raise EventConsumerIdempotencyError("operation is not covered")
        return object()


class _Consumer:
    def __init__(
        self,
        consumer_id: str,
        outcomes: dict[str, ConsumerOutcome | BaseException | object] | None = None,
    ) -> None:
        self.consumer_id = consumer_id
        self.outcomes = outcomes or {}
        self.calls: list[tuple[StoredEvent, ConsumerDeliveryContext]] = []

    def consume(
        self,
        event: StoredEvent,
        context: ConsumerDeliveryContext,
    ) -> ConsumerOutcome:
        self.calls.append((event, context))
        result = self.outcomes.get(event.event_id, ConsumerOutcome.ack())
        if isinstance(result, BaseException):
            raise result
        return result  # type: ignore[return-value]


class _TraceConsumer(_Consumer):
    def __init__(self, consumer_id: str) -> None:
        super().__init__(consumer_id)
        self.trace_contexts: list[W3CSpanContext | None] = []

    def consume(
        self,
        event: StoredEvent,
        context: ConsumerDeliveryContext,
    ) -> ConsumerOutcome:
        active = current_trace_context()
        self.trace_contexts.append(
            active if isinstance(active, W3CSpanContext) else None
        )
        return super().consume(event, context)


class _TelemetryScope(AbstractContextManager[None]):
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: Any, exc: BaseException | None, traceback: Any) -> bool:
        return False


class _TraceTelemetry:
    def __init__(self) -> None:
        self.started: list[dict[str, Any]] = []

    def start_span(self, name: str, *, attributes: Any, links: Any) -> _TelemetryScope:
        self.started.append(
            {
                "name": name,
                "attributes": dict(attributes),
                "links": tuple(link for link in links if link is not None),
            }
        )
        return _TelemetryScope()


class _MetricBackend:
    def __init__(self) -> None:
        self.counters: list[tuple[str, int, dict[str, str]]] = []
        self.gauges: list[tuple[str, float, dict[str, str]]] = []

    def add_counter(self, name, value, *, attributes) -> None:
        self.counters.append((name, value, dict(attributes)))

    def record_histogram(self, name, value, *, attributes) -> None:
        return None

    def record_gauge(self, name, value, *, attributes) -> None:
        self.gauges.append((name, value, dict(attributes)))

    def start_span(self, name, *, attributes, links) -> _TelemetryScope:
        return _TelemetryScope()


class _RedeliveryAuthorizer:
    def __init__(
        self,
        *,
        trace: list[str] | None = None,
        authorized: bool = True,
        error: Exception | None = None,
        invalid_response: object | None = None,
        bind_to: RedeliveryAuthorizationRequest | None = None,
        tamper_request_checksum: bool = False,
        tamper_decision_checksum: bool = False,
    ) -> None:
        self.trace = trace if trace is not None else []
        self.authorized = authorized
        self.error = error
        self.invalid_response = invalid_response
        self.bind_to = bind_to
        self.tamper_request_checksum = tamper_request_checksum
        self.tamper_decision_checksum = tamper_decision_checksum
        self.requests: list[RedeliveryAuthorizationRequest] = []

    def authorize(
        self,
        request: RedeliveryAuthorizationRequest,
    ) -> RedeliveryAuthorizationDecision:
        self.trace.append("authorize")
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        if self.invalid_response is not None:
            return self.invalid_response  # type: ignore[return-value]
        bound_request = self.bind_to or request
        if self.tamper_request_checksum:
            object.__setattr__(bound_request, "request_checksum", "sha256:" + "0" * 64)
        decision = RedeliveryAuthorizationDecision(
            request=bound_request,
            authorized=self.authorized,
            decided_at=bound_request.requested_at,
            authorization_evidence_ref=(
                bound_request.authorization_evidence_ref
                if self.authorized
                else None
            ),
            denial_reason_class=None if self.authorized else "operator_not_authorized",
        )
        if self.tamper_decision_checksum:
            object.__setattr__(decision, "decision_checksum", "sha256:" + "0" * 64)
        return decision


class _IdempotentTargetConsumer(_Consumer):
    def __init__(self, consumer_id: str) -> None:
        super().__init__(consumer_id)
        self.applied_keys: set[str] = set()

    @property
    def applied_count(self) -> int:
        return len(self.applied_keys)

    def consume(
        self,
        event: StoredEvent,
        context: ConsumerDeliveryContext,
    ) -> ConsumerOutcome:
        self.calls.append((event, context))
        assert context.idempotency_key is not None
        self.applied_keys.add(context.idempotency_key)
        return ConsumerOutcome.ack()


class _TransactionalConsumer(_Consumer):
    def __init__(self, consumer_id: str) -> None:
        super().__init__(consumer_id)
        self.applied_keys: set[str] = set()

    @property
    def applied_count(self) -> int:
        return len(self.applied_keys)

    def consume(
        self,
        event: StoredEvent,
        context: ConsumerDeliveryContext,
    ) -> ConsumerOutcome:
        self.calls.append((event, context))
        assert context.idempotency_key is not None
        self.applied_keys.add(context.idempotency_key)
        return ConsumerOutcome.ack()


class _SecretClassifier:
    def __init__(self, secret: str) -> None:
        self.secret = secret

    def classify(self, error: BaseException) -> ConsumerFailure:
        del error
        return ConsumerFailure(
            kind=ConsumerFailureKind.TRANSIENT,
            reason_class=f"database_{self.secret}",
            redacted_diagnostic=f"Authorization: Bearer {self.secret}",
        )


class _ThrowingClassifier:
    def classify(self, error: BaseException) -> ConsumerFailure:
        del error
        raise PermanentEventProcessingError("classifier_failed")


class _InvalidClassifier:
    def classify(self, error: BaseException) -> ConsumerFailure:
        del error
        return {"kind": "permanent"}  # type: ignore[return-value]


class _Store:
    def __init__(self, trace: list[str] | None = None) -> None:
        self.trace = trace if trace is not None else []
        self.subscriptions: dict[SubscriptionKey, DurableSubscription] = {}
        self.claims: list[ClaimedDelivery] = []
        self.inbox: dict[InboxKey, InboxEntry] = {}
        self.settlements: list[DeliverySettlement] = []
        self.status_changes: list[
            tuple[SubscriptionKey, SubscriptionStatus, datetime, str]
        ] = []
        self.last_claim_request: DeliveryClaimRequest | None = None
        self.fail_registration = False
        self.claim_error: Exception | None = None
        self.fail_settlement_ids: set[str] = set()
        self.dead_letters: dict[str, DeadLetterRecord] = {}
        self.requeued: list[DeadLetterAction] = []
        self.redelivery_requests: list[RedeliveryRequest] = []
        self.pending_stats = PendingDeliveryStats(pending_count=0, lag=0)

    def register_subscription(
        self,
        subscription: DurableSubscription,
    ) -> DurableSubscription:
        self.trace.append("store")
        if self.fail_registration:
            raise RuntimeError("registration unavailable")
        existing = self.subscriptions.get(subscription.key)
        if existing is not None:
            return existing
        persisted = replace(
            subscription,
            created_at=subscription.created_at or NOW,
            updated_at=subscription.updated_at or NOW,
        )
        self.subscriptions[persisted.key] = persisted
        return persisted

    def get_subscription(self, key: SubscriptionKey) -> DurableSubscription | None:
        return self.subscriptions.get(key)

    def set_subscription_status(
        self,
        key: SubscriptionKey,
        status: SubscriptionStatus,
        *,
        changed_at: datetime,
        reason: str,
    ) -> DurableSubscription:
        subscription = self.subscriptions[key]
        updated = replace(subscription, status=status, updated_at=changed_at)
        self.subscriptions[key] = updated
        self.status_changes.append((key, status, changed_at, reason))
        return updated

    def claim_deliveries(
        self,
        request: DeliveryClaimRequest,
    ) -> tuple[ClaimedDelivery, ...]:
        self.last_claim_request = request
        if self.claim_error is not None:
            raise self.claim_error
        selected = tuple(self.claims[: request.limit])
        del self.claims[: request.limit]
        return selected

    def pending_delivery_stats(
        self,
        key: SubscriptionKey,
        *,
        stream_id: str | None = None,
    ) -> PendingDeliveryStats:
        del key, stream_id
        return self.pending_stats

    def get_inbox_entry(
        self,
        key: InboxKey,
        *,
        tenant_id: str | None = None,
    ) -> InboxEntry | None:
        del tenant_id
        return self.inbox.get(key)

    def settle_delivery(
        self,
        settlement: DeliverySettlement,
    ) -> DeliverySettlementResult:
        if settlement.lease.delivery_id in self.fail_settlement_ids:
            raise RuntimeError("postgres failed with secret-token-value")
        self.settlements.append(settlement)
        claim = next(
            claim
            for claim in self._all_known_claims
            if claim.delivery.delivery_id == settlement.lease.delivery_id
        )
        delivery = claim.delivery
        first_failure = delivery.first_failure_at
        last_failure = delivery.last_failure_at
        if settlement.target_state in {
            DeliveryState.RETRY_WAIT,
            DeliveryState.DEAD_LETTER,
        }:
            first_failure = first_failure or settlement.settled_at
            last_failure = settlement.settled_at
        updated = replace(
            delivery,
            state=settlement.target_state,
            available_at=settlement.retry_available_at,
            lease_owner=None,
            lease_generation=None,
            lease_expires_at=None,
            first_failure_at=first_failure,
            last_failure_at=last_failure,
            reason_class=settlement.reason_class,
            redacted_diagnostic=settlement.redacted_diagnostic,
            updated_at=settlement.settled_at,
        )
        inbox_recorded = False
        if settlement.inbox_entry is not None:
            key = settlement.inbox_entry.key
            existing = self.inbox.get(key)
            if existing is None:
                self.inbox[key] = settlement.inbox_entry
                inbox_recorded = True
            elif existing.result_checksum != settlement.inbox_entry.result_checksum:
                raise EventConsumerIdempotencyError("inbox checksum collision")
        return DeliverySettlementResult(
            delivery=updated,
            dead_letter_id=(
                f"dlq:{delivery.delivery_id}"
                if updated.state is DeliveryState.DEAD_LETTER
                else None
            ),
            inbox_recorded=inbox_recorded,
        )

    @property
    def _all_known_claims(self) -> tuple[ClaimedDelivery, ...]:
        return tuple(_CLAIM_INDEX.values())

    def get_dead_letter(
        self,
        dead_letter_id: str,
        *,
        tenant_id: str | None = None,
    ) -> DeadLetterRecord | None:
        record = self.dead_letters.get(dead_letter_id)
        if record is not None and record.tenant_id != tenant_id:
            return None
        return record

    def requeue_dead_letter(self, action: DeadLetterAction) -> DeliveryRecord:
        record = self.dead_letters[action.dead_letter_id]
        self.requeued.append(action)
        return DeliveryRecord(
            delivery_id=f"repair:{record.delivery_id}",
            event_id=record.event_id,
            stream_id=record.stream_id,
            stream_sequence=record.stream_sequence,
            subscription_id=record.subscription_id,
            subscription_version=record.subscription_version,
            consumer_id=record.consumer_id,
            consumer_effect_id=record.consumer_effect_id,
            tenant_id=record.tenant_id,
            delivery_generation=record.delivery_generation + 1,
            state=DeliveryState.PENDING,
            attempt_count=0,
            available_at=action.requested_at,
            created_at=action.requested_at,
            updated_at=action.requested_at,
        )

    def begin_redelivery(self, request: RedeliveryRequest) -> RedeliveryReport:
        self.trace.append("store")
        self.redelivery_requests.append(request)
        subscription = self.subscriptions[request.subscription]
        through_sequence = request.through_sequence or 1
        return RedeliveryReport(
            redelivery_id=request.redelivery_id,
            subscription=request.subscription,
            source_stream_id=request.source_stream_id,
            from_sequence=request.from_sequence,
            requested_through_sequence=request.through_sequence,
            through_sequence=through_sequence,
            captured_high_watermark=through_sequence,
            requested_at=request.requested_at,
            scheduled_at=request.requested_at,
            operator_id=request.operator_id,
            operator_reason=request.operator_reason,
            authorization_evidence_ref=request.authorization_evidence_ref,
            tenant_id=request.tenant_id,
            items=(
                RedeliveryItem(
                    redelivery_id=request.redelivery_id,
                    event_id="evt-redelivery",
                    stream_id=request.source_stream_id,
                    stream_sequence=request.from_sequence,
                    subscription=request.subscription,
                    delivery_id="delivery-redelivery-v2",
                    delivery_generation=2,
                    created_at=request.requested_at,
                    tenant_id=request.tenant_id,
                ),
            ),
        )


class _InboxTransactionRunner:
    runner_id = "fake-shared-effect-transaction/v1"

    def __init__(self, store: _Store) -> None:
        self.store = store
        self.validations = 0

    def validate(
        self,
        subscription: DurableSubscription,
    ) -> InboxTransactionCapability:
        self.validations += 1
        assert subscription.effect.consumer_effect_id is not None
        return InboxTransactionCapability(
            subscription_id=subscription.subscription_id,
            subscription_version=subscription.subscription_version,
            consumer_id=subscription.consumer_id,
            consumer_effect_id=subscription.effect.consumer_effect_id,
            subscription_fingerprint=subscription_definition_fingerprint(
                subscription
            ),
            runner_id=self.runner_id,
            validated_at=NOW,
        )

    def execute(
        self,
        *,
        subscription: DurableSubscription,
        consumer: _Consumer,
        claimed: ClaimedDelivery,
        context: ConsumerDeliveryContext,
        settled_at: datetime,
    ) -> InboxTransactionResult:
        effect_id = subscription.effect.consumer_effect_id
        assert effect_id is not None
        inbox_key = InboxKey(claimed.event.event_id, effect_id)
        existing = self.store.inbox.get(inbox_key)
        if existing is not None:
            settlement = DeliverySettlement(
                lease=claimed.lease,
                target_state=DeliveryState.ACKED,
                settled_at=settled_at,
                reason_class="effect_already_completed",
                inbox_entry=InboxEntry(
                    event_id=claimed.event.event_id,
                    consumer_effect_id=effect_id,
                    completed_at=settled_at,
                    delivery_id=claimed.delivery.delivery_id,
                    result_checksum=existing.result_checksum,
                ),
            )
            result = self.store.settle_delivery(settlement)
            return InboxTransactionResult(
                consumer_called=False,
                inbox_already_completed=True,
                outcome=ConsumerOutcome.ack(),
                settlement=result,
            )

        inbox_snapshot = dict(self.store.inbox)
        settlement_count = len(self.store.settlements)
        effects = getattr(consumer, "applied_keys", None)
        effect_snapshot = None if effects is None else set(effects)
        try:
            outcome = consumer.consume(claimed.event, context)
            if not isinstance(outcome, ConsumerOutcome):
                raise TypeError("invalid transactional consumer outcome")
            if outcome.disposition is not ConsumerDisposition.ACK:
                if effects is not None and effect_snapshot is not None:
                    effects.clear()
                    effects.update(effect_snapshot)
                return InboxTransactionResult(
                    consumer_called=True,
                    inbox_already_completed=False,
                    outcome=outcome,
                )
            settlement = DeliverySettlement(
                lease=claimed.lease,
                target_state=DeliveryState.ACKED,
                settled_at=settled_at,
                reason_class="effect_completed",
                inbox_entry=InboxEntry(
                    event_id=claimed.event.event_id,
                    consumer_effect_id=effect_id,
                    completed_at=settled_at,
                    delivery_id=claimed.delivery.delivery_id,
                ),
            )
            result = self.store.settle_delivery(settlement)
        except Exception:
            self.store.inbox = inbox_snapshot
            del self.store.settlements[settlement_count:]
            if effects is not None and effect_snapshot is not None:
                effects.clear()
                effects.update(effect_snapshot)
            raise
        return InboxTransactionResult(
            consumer_called=True,
            inbox_already_completed=False,
            outcome=outcome,
            settlement=result,
        )


_CLAIM_INDEX: dict[str, ClaimedDelivery] = {}


def _event(
    number: int,
    *,
    stream_id: str | None = None,
    tenant_id: str | None = None,
    event_type: str = "io.newsroom.test.delivery",
    trace: TraceBlock | None = None,
) -> StoredEvent:
    candidate = EventCandidate(
        event_id=f"evt-delivery-{number}",
        event_type=event_type,
        data_schema="io.newsroom.test.delivery/v1",
        source="tests.delivery",
        occurred_at=NOW - timedelta(minutes=1),
        stream_id=stream_id or f"run:delivery-{number}",
        business_context=BusinessContext(run_id=f"delivery-{number}"),
        producer=ProducerIdentity(component="delivery-test", version="1"),
        trace=trace,
        tenant_id=tenant_id,
        payload={"sequence": number},
    )
    return StoredEvent(
        candidate,
        observed_at=NOW - timedelta(seconds=30),
        stream_sequence=number,
    )


def _claim(
    event: StoredEvent,
    subscription: DurableSubscription,
    *,
    attempt_count: int = 1,
    delivery_generation: int = 1,
) -> ClaimedDelivery:
    delivery_id = (
        f"delivery:{subscription.subscription_id}:"
        f"{event.event_id}:{delivery_generation}:{attempt_count}"
    )
    lease = DeliveryLeaseToken(
        delivery_id=delivery_id,
        delivery_generation=delivery_generation,
        lease_owner="worker-1",
        lease_generation=attempt_count,
        lease_expires_at=NOW + timedelta(minutes=5),
        lease_started_at=NOW,
    )
    delivery = DeliveryRecord(
        delivery_id=delivery_id,
        event_id=event.event_id,
        stream_id=event.stream_id,
        stream_sequence=event.stream_sequence,
        subscription_id=subscription.subscription_id,
        subscription_version=subscription.subscription_version,
        consumer_id=subscription.consumer_id,
        consumer_effect_id=subscription.effect.consumer_effect_id,
        tenant_id=subscription.tenant_id,
        delivery_generation=delivery_generation,
        state=DeliveryState.CLAIMED,
        attempt_count=attempt_count,
        lease_owner=lease.lease_owner,
        lease_generation=lease.lease_generation,
        lease_expires_at=lease.lease_expires_at,
        created_at=NOW - timedelta(seconds=10),
        updated_at=NOW,
    )
    claimed = ClaimedDelivery(delivery=delivery, event=event, lease=lease)
    _CLAIM_INDEX[delivery_id] = claimed
    return claimed


def _subscription(
    *,
    version: int = 1,
    external: bool = False,
    strategy: EffectIdempotencyStrategy = (
        EffectIdempotencyStrategy.TARGET_IDEMPOTENCY_KEY
    ),
    supports_repair: bool = False,
    tenant_id: str | None = None,
    retry_policy: RetryPolicy | None = None,
    limits: DeliveryLimits | None = None,
) -> DurableSubscription:
    effect = (
        ConsumerEffectContract(
            performs_external_effects=True,
            consumer_effect_id="report-publication",
            idempotency_strategy=strategy,
        )
        if external
        else ConsumerEffectContract()
    )
    return DurableSubscription(
        subscription_id="report-publication",
        subscription_version=version,
        consumer_id="report-publisher",
        event_filter=SubscriptionFilter(
            event_types=frozenset({"io.newsroom.test.delivery"})
        ),
        start=SubscriptionStart(SubscriptionStartPolicy.EARLIEST),
        effect=effect,
        retry_policy=retry_policy or RetryPolicy(jitter_ratio=0),
        limits=limits or DeliveryLimits(),
        supports_out_of_order_repair=supports_repair,
        tenant_id=tenant_id,
    )


def _runtime(
    store: _Store,
    subscription: DurableSubscription,
    consumer: _Consumer,
    *,
    gate: _CapabilityGate | None = None,
    inbox_runner: _InboxTransactionRunner | None = None,
    drop_policy: StaticDropAuthorizationPolicy | None = None,
    clock: _Clock | _SequenceClock | None = None,
    error_classifier: ConsumerErrorClassifier | None = None,
    diagnostic_fallback: LocalRuntimeDiagnosticFallback | None = None,
    authorizer: _RedeliveryAuthorizer | None = None,
    telemetry: EventTelemetry | None = None,
) -> DurableDeliveryRuntime:
    runtime = DurableDeliveryRuntime(
        store,  # type: ignore[arg-type]
        idempotency_capabilities=gate,  # type: ignore[arg-type]
        inbox_transaction_runner=inbox_runner,
        drop_policy=drop_policy,
        error_classifier=error_classifier,
        diagnostic_fallback=diagnostic_fallback,
        redelivery_authorizer=authorizer,
        telemetry=telemetry,
        clock=clock or _Clock(),
    )
    runtime.register(subscription, consumer)
    return runtime


def test_registration_validates_effect_capability_before_durable_persistence() -> None:
    trace: list[str] = []
    store = _Store(trace)
    gate = _CapabilityGate(trace)
    subscription = _subscription(external=True)
    consumer = _Consumer(subscription.consumer_id)
    registry = DurableConsumerRegistry(
        store,  # type: ignore[arg-type]
        idempotency_capabilities=gate,  # type: ignore[arg-type]
        clock=_Clock(),
    )

    persisted = registry.register(subscription, consumer)

    assert trace == ["capability", "store"]
    assert persisted.key in registry.registered_keys
    assert persisted.start.policy is SubscriptionStartPolicy.EARLIEST
    assert gate.validated == [subscription.key]


def test_inbox_transaction_without_composed_runner_fails_before_registration() -> None:
    store = _Store()
    gate = _CapabilityGate()
    subscription = _subscription(
        external=True,
        strategy=EffectIdempotencyStrategy.INBOX_TRANSACTION,
    )
    consumer = _Consumer(subscription.consumer_id)
    runtime = DurableDeliveryRuntime(
        store,  # type: ignore[arg-type]
        idempotency_capabilities=gate,  # type: ignore[arg-type]
        clock=_Clock(),
    )

    with pytest.raises(EventConsumerIdempotencyError, match="transactional effect"):
        runtime.register(subscription, consumer)

    assert store.subscriptions == {}
    assert runtime.consumers.registered_keys == ()


def test_inbox_runner_validation_error_does_not_expose_raw_exception_chain() -> None:
    secret = "inbox-validator-secret"

    class _FailingRunner:
        runner_id = "failing-runner/v1"

        def validate(self, subscription: DurableSubscription) -> None:
            del subscription
            raise RuntimeError(secret)

        def execute(self, **kwargs: object) -> InboxTransactionResult:
            del kwargs
            raise AssertionError("execute must not be called")

    store = _Store()
    gate = _CapabilityGate()
    subscription = _subscription(
        external=True,
        strategy=EffectIdempotencyStrategy.INBOX_TRANSACTION,
    )
    runtime = DurableDeliveryRuntime(
        store,  # type: ignore[arg-type]
        idempotency_capabilities=gate,  # type: ignore[arg-type]
        inbox_transaction_runner=_FailingRunner(),  # type: ignore[arg-type]
        clock=_Clock(),
    )

    with pytest.raises(EventConsumerIdempotencyError) as captured:
        runtime.register(subscription, _Consumer(subscription.consumer_id))

    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert secret not in "".join(traceback.format_exception(captured.value))
    assert store.subscriptions == {}


def test_failed_registration_or_consumer_mismatch_never_creates_a_binding() -> None:
    store = _Store()
    store.fail_registration = True
    subscription = _subscription()
    consumer = _Consumer(subscription.consumer_id)
    registry = DurableConsumerRegistry(store, clock=_Clock())  # type: ignore[arg-type]

    with pytest.raises(EventDeliveryStoreOperationError, match="registration failed"):
        registry.register(subscription, consumer)
    assert registry.registered_keys == ()

    store.fail_registration = False
    with pytest.raises(EventConsumerMismatchError, match="consumer_id"):
        registry.register(subscription, _Consumer("different-consumer"))
    assert store.subscriptions == {}


def test_missing_store_subscription_and_attached_consumer_have_typed_failures() -> None:
    subscription = _subscription()
    consumer = _Consumer(subscription.consumer_id)
    missing_store = DurableConsumerRegistry(None, clock=_Clock())

    with pytest.raises(EventDeliveryConfigurationError, match="event store"):
        missing_store.register(subscription, consumer)

    store = _Store()
    registry = DurableConsumerRegistry(store, clock=_Clock())  # type: ignore[arg-type]
    with pytest.raises(EventSubscriptionNotFoundError):
        registry.attach(subscription.key, consumer)

    store.subscriptions[subscription.key] = subscription
    with pytest.raises(EventConsumerNotRegisteredError):
        registry.resolve(subscription.key)

    another_store = _Store()
    with pytest.raises(EventDeliveryConfigurationError, match="share one event store"):
        DurableDeliveryRuntime(
            another_store,  # type: ignore[arg-type]
            consumers=registry,
        )


def test_subscription_versions_and_status_transitions_remain_independent() -> None:
    store = _Store()
    registry = DurableConsumerRegistry(store, clock=_Clock())  # type: ignore[arg-type]
    consumer = _Consumer("report-publisher")
    earliest = _subscription(version=1)
    latest = replace(
        _subscription(version=2),
        start=SubscriptionStart(SubscriptionStartPolicy.LATEST),
    )
    registry.register(earliest, consumer)
    registry.register(latest, consumer)

    paused = registry.pause(earliest.key, reason="maintenance")
    resumed = registry.resume(earliest.key, reason="maintenance complete")
    retired = registry.retire(latest.key, reason="superseded")

    assert paused.status is SubscriptionStatus.PAUSED
    assert resumed.status is SubscriptionStatus.ACTIVE
    assert retired.status is SubscriptionStatus.RETIRED
    assert store.subscriptions[earliest.key].status is SubscriptionStatus.ACTIVE
    assert store.subscriptions[latest.key].status is SubscriptionStatus.RETIRED
    assert all(change[2] == NOW for change in store.status_changes)


def test_emergency_pause_and_retire_do_not_require_local_consumer_binding() -> None:
    store = _Store()
    subscription = _subscription()
    store.subscriptions[subscription.key] = subscription
    registry = DurableConsumerRegistry(store, clock=_Clock())  # type: ignore[arg-type]

    paused = registry.pause(subscription.key, reason="consumer unavailable")
    retired = registry.retire(subscription.key, reason="version withdrawn")

    assert paused.status is SubscriptionStatus.PAUSED
    assert retired.status is SubscriptionStatus.RETIRED
    assert registry.registered_keys == ()
    with pytest.raises(EventConsumerNotRegisteredError):
        registry.resume(subscription.key, reason="unsafe without worker binding")


def test_ack_maps_to_atomic_settlement_and_bounded_claim_request() -> None:
    store = _Store()
    subscription = _subscription(
        limits=DeliveryLimits(batch_size=2, max_in_flight=3)
    )
    consumer = _Consumer(subscription.consumer_id)
    runtime = _runtime(store, subscription, consumer)
    store.claims.extend(
        [_claim(_event(number), subscription) for number in range(1, 4)]
    )

    result = runtime.dispatch_batch(
        subscription.key,
        lease_owner="worker-1",
        limit=50,
    )

    assert result.claimed_count == 2
    assert result.acknowledged_count == 2
    assert result.processing_failure_count == 0
    assert store.last_claim_request is not None
    assert store.last_claim_request.limit == 2
    assert len(consumer.calls) == 2
    assert all(
        settlement.target_state is DeliveryState.ACKED
        for settlement in store.settlements
    )


def test_delivery_batch_and_retry_use_origin_links_and_scoped_children() -> None:
    first_origin = W3CSpanContext.root()
    second_origin = W3CSpanContext.root()
    first = _event(
        1,
        trace=TraceBlock(
            trace_id=first_origin.trace_id,
            span_id=first_origin.span_id,
        ),
    )
    second = _event(
        2,
        trace=TraceBlock(
            trace_id=second_origin.trace_id,
            span_id=second_origin.span_id,
        ),
    )
    subscription = _subscription()
    store = _Store()
    store.claims = [
        _claim(first, subscription),
        _claim(second, subscription, attempt_count=2),
    ]
    consumer = _TraceConsumer(subscription.consumer_id)
    telemetry = _TraceTelemetry()
    runtime = DurableDeliveryRuntime(
        store,  # type: ignore[arg-type]
        telemetry=telemetry,  # type: ignore[arg-type]
        clock=_Clock(),
    )
    runtime.register(subscription, consumer)

    result = runtime.dispatch_batch(
        subscription.key,
        lease_owner="worker-1",
        limit=2,
    )

    assert result.acknowledged_count == 2
    batch = next(
        span
        for span in telemetry.started
        if span["name"] == "newsroom.event.delivery.batch"
    )
    assert {link.context.trace_id for link in batch["links"]} == {
        first_origin.trace_id,
        second_origin.trace_id,
    }
    consume_spans = [
        span
        for span in telemetry.started
        if span["name"] == "newsroom.event.delivery.consume"
    ]
    assert [
        span["links"][0].attributes["newsroom.link.relationship"]
        for span in consume_spans
    ] == ["event_delivery", "delivery_retry"]
    assert [context.trace_id for context in consumer.trace_contexts if context] == [
        first_origin.trace_id,
        second_origin.trace_id,
    ]
    assert [
        context.parent_span_id for context in consumer.trace_contexts if context
    ] == [first_origin.span_id, second_origin.span_id]


def test_delivery_records_attempt_dead_letter_lease_and_backlog_metrics() -> None:
    subscription = replace(
        _subscription(),
        consumer_id="workflow-consumer",
    )
    first = _claim(_event(1), subscription, attempt_count=2)
    first = replace(
        first,
        delivery=replace(
            first.delivery,
            first_failure_at=NOW - timedelta(seconds=30),
            last_failure_at=NOW - timedelta(seconds=30),
            reason_class="lease_expired",
        ),
    )
    second = _claim(_event(2), subscription)
    store = _Store()
    store.claims = [first, second]
    store.pending_stats = PendingDeliveryStats(
        pending_count=3,
        lag=3,
        oldest_pending_at=NOW - timedelta(seconds=15),
        oldest_pending_age_seconds=15,
    )
    consumer = _Consumer(
        subscription.consumer_id,
        outcomes={
            second.event.event_id: PermanentEventProcessingError("permanent failure")
        },
    )
    backend = _MetricBackend()
    runtime = _runtime(
        store,
        subscription,
        consumer,
        telemetry=EventTelemetry(backend),
    )

    result = runtime.dispatch_batch(
        subscription.key,
        lease_owner="worker-1",
        limit=2,
    )

    assert result.acknowledged_count == 1
    assert result.dead_lettered_count == 1
    assert backend.counters == [
        (
            "event_delivery_attempt_total",
            1,
            {"consumer": "workflow", "outcome": "ack"},
        ),
        ("event_lease_recovery_total", 1, {"consumer": "workflow"}),
        (
            "event_delivery_attempt_total",
            1,
            {"consumer": "workflow", "outcome": "dead_letter"},
        ),
        (
            "event_dead_letter_total",
            1,
            {"consumer": "workflow", "reason_class": "permanent"},
        ),
    ]
    backlog = [
        item
        for item in backend.gauges
        if item[0].startswith("event_delivery_")
    ]
    assert backlog == [
        ("event_delivery_pending", 3.0, {"consumer": "workflow"}),
        ("event_delivery_lag", 3.0, {"consumer": "workflow"}),
        (
            "event_delivery_oldest_age_seconds",
            15.0,
            {"consumer": "workflow"},
        ),
    ]


def test_inbox_transaction_writes_stable_entry_and_redelivery_skips_effect() -> None:
    store = _Store()
    gate = _CapabilityGate()
    subscription = _subscription(
        external=True,
        strategy=EffectIdempotencyStrategy.INBOX_TRANSACTION,
        supports_repair=True,
    )
    consumer = _Consumer(subscription.consumer_id)
    runner = _InboxTransactionRunner(store)
    runtime = _runtime(
        store,
        subscription,
        consumer,
        gate=gate,
        inbox_runner=runner,
    )
    event = _event(1)
    first = _claim(event, subscription)
    store.claims.append(first)

    accepted = runtime.dispatch_batch(subscription.key, lease_owner="worker-1")

    inbox_key = InboxKey(event.event_id, "report-publication")
    assert accepted.acknowledged_count == 1
    assert accepted.inbox_deduplicated_count == 0
    assert store.inbox[inbox_key].delivery_id == first.delivery.delivery_id
    assert consumer.calls[0][1].idempotency_key == effect_idempotency_key(
        event.event_id,
        "report-publication",
    )

    repair = _claim(event, subscription, delivery_generation=2)
    store.claims.append(repair)
    deduplicated = runtime.dispatch_batch(
        subscription.key,
        lease_owner="worker-1",
    )

    assert deduplicated.acknowledged_count == 1
    assert deduplicated.inbox_deduplicated_count == 1
    assert not deduplicated.attempts[0].consumer_called
    assert len(consumer.calls) == 1
    assert gate.required[-1] is AutomaticDeliveryOperation.REDELIVERY


def test_inbox_transaction_rolls_back_effect_when_ack_settlement_fails() -> None:
    store = _Store()
    gate = _CapabilityGate()
    subscription = _subscription(
        external=True,
        strategy=EffectIdempotencyStrategy.INBOX_TRANSACTION,
    )
    consumer = _TransactionalConsumer(subscription.consumer_id)
    runner = _InboxTransactionRunner(store)
    runtime = _runtime(
        store,
        subscription,
        consumer,
        gate=gate,
        inbox_runner=runner,
    )
    event = _event(1)
    first = _claim(event, subscription)
    store.fail_settlement_ids.add(first.delivery.delivery_id)
    store.claims.append(first)

    failed = runtime.dispatch_batch(subscription.key, lease_owner="worker-1")

    assert failed.processing_failure_count == 1
    assert consumer.applied_count == 0
    assert store.inbox == {}

    store.fail_settlement_ids.clear()
    recovered = _claim(event, subscription, attempt_count=2)
    store.claims.append(recovered)
    accepted = runtime.dispatch_batch(subscription.key, lease_owner="worker-1")

    assert accepted.acknowledged_count == 1
    assert consumer.applied_count == 1
    assert len(consumer.calls) == 2
    assert len(store.inbox) == 1


def test_target_idempotency_key_prevents_duplicate_effect_after_settlement_failure() -> None:
    store = _Store()
    gate = _CapabilityGate()
    subscription = _subscription(external=True)
    consumer = _IdempotentTargetConsumer(subscription.consumer_id)
    runtime = _runtime(store, subscription, consumer, gate=gate)
    event = _event(1)
    first = _claim(event, subscription)
    store.fail_settlement_ids.add(first.delivery.delivery_id)
    store.claims.append(first)

    failed = runtime.dispatch_batch(subscription.key, lease_owner="worker-1")

    assert failed.processing_failure_count == 1
    assert consumer.applied_count == 1

    store.fail_settlement_ids.clear()
    recovered = _claim(event, subscription, attempt_count=2)
    store.claims.append(recovered)
    accepted = runtime.dispatch_batch(subscription.key, lease_owner="worker-1")

    assert accepted.acknowledged_count == 1
    assert len(consumer.calls) == 2
    assert consumer.applied_count == 1
    assert (
        consumer.calls[0][1].idempotency_key
        == consumer.calls[1][1].idempotency_key
    )


def test_retry_permanent_failure_and_authorized_drop_map_to_durable_states() -> None:
    store = _Store()
    subscription = _subscription()
    events = [_event(number) for number in range(1, 4)]
    consumer = _Consumer(
        subscription.consumer_id,
        outcomes={
            events[0].event_id: ConsumerOutcome.retry(
                "backend_unavailable",
                "timeout_code",
            ),
            events[1].event_id: PermanentEventProcessingError(
                "unsupported_payload",
                redacted_diagnostic="schema_code",
            ),
            events[2].event_id: ConsumerOutcome.drop("not_relevant"),
        },
    )
    drop_policy = StaticDropAuthorizationPolicy(
        [
            DropAuthorizationRule(
                reason_class="not_relevant",
                consumer_ids=frozenset({subscription.consumer_id}),
                event_types=frozenset({"io.newsroom.test.delivery"}),
            )
        ]
    )
    runtime = _runtime(
        store,
        subscription,
        consumer,
        drop_policy=drop_policy,
    )
    store.claims.extend(_claim(event, subscription) for event in events)

    result = runtime.dispatch_batch(subscription.key, lease_owner="worker-1")

    assert result.retry_scheduled_count == 1
    assert result.dead_lettered_count == 1
    assert result.dropped_count == 1
    assert [item.state for item in result.attempts] == [
        DeliveryState.RETRY_WAIT,
        DeliveryState.DEAD_LETTER,
        DeliveryState.DROPPED,
    ]
    assert store.settlements[0].retry_available_at == NOW + timedelta(seconds=1)
    assert store.settlements[0].reason_class == "consumer_requested_retry"
    assert store.settlements[1].reason_class == "permanent_processing_failure"
    assert all(
        settlement.redacted_diagnostic is not None
        and settlement.redacted_diagnostic.startswith("redacted:sha256:")
        for settlement in store.settlements
    )
    assert "timeout_code" not in repr(store.settlements)
    assert "schema_code" not in repr(store.settlements)


def test_unauthorized_drop_is_a_permanent_dead_letter_not_a_skip() -> None:
    store = _Store()
    subscription = _subscription()
    event = _event(1)
    consumer = _Consumer(
        subscription.consumer_id,
        {event.event_id: ConsumerOutcome.drop("ignore_failure")},
    )
    runtime = _runtime(store, subscription, consumer)
    store.claims.append(_claim(event, subscription))

    result = runtime.dispatch_batch(subscription.key, lease_owner="worker-1")

    assert result.dead_lettered_count == 1
    assert store.settlements[0].reason_class == "unapproved_drop"
    assert store.settlements[0].redacted_diagnostic is not None
    assert store.settlements[0].redacted_diagnostic.startswith("redacted:sha256:")
    assert "drop_policy_denied" not in repr(store.settlements)


def test_unhandled_exception_is_redacted_and_does_not_block_other_streams() -> None:
    secret = "credential-that-must-never-be-persisted"
    store = _Store()
    subscription = _subscription()
    failed = _event(1, stream_id="run:failed")
    healthy = _event(2, stream_id="run:healthy")
    consumer = _Consumer(
        subscription.consumer_id,
        {failed.event_id: RuntimeError(f"backend exposed {secret}")},
    )
    runtime = _runtime(store, subscription, consumer)
    store.claims.extend(
        [_claim(failed, subscription), _claim(healthy, subscription)]
    )

    result = runtime.dispatch_batch(subscription.key, lease_owner="worker-1")

    assert result.retry_scheduled_count == 1
    assert result.acknowledged_count == 1
    retry = store.settlements[0]
    assert retry.reason_class == "transient_processing_failure"
    assert retry.redacted_diagnostic is not None
    assert retry.redacted_diagnostic.startswith("redacted:sha256:")
    assert secret not in repr(result)
    assert secret not in repr(store.settlements)


def test_explicit_outcome_and_custom_classifier_secrets_are_projected() -> None:
    secret = "api-token-super-secret"
    store = _Store()
    subscription = _subscription()
    explicit = _event(1, stream_id="run:explicit-secret")
    classified = _event(2, stream_id="run:classifier-secret")
    consumer = _Consumer(
        subscription.consumer_id,
        {
            explicit.event_id: ConsumerOutcome.retry(
                f"authorization_{secret}",
                f"Authorization: Bearer {secret}",
            ),
            classified.event_id: RuntimeError(secret),
        },
    )
    runtime = _runtime(
        store,
        subscription,
        consumer,
        error_classifier=_SecretClassifier(secret),
    )
    store.claims.extend(
        [_claim(explicit, subscription), _claim(classified, subscription)]
    )

    result = runtime.dispatch_batch(subscription.key, lease_owner="worker-1")

    assert result.retry_scheduled_count == 2
    assert [item.reason_class for item in store.settlements] == [
        "consumer_requested_retry",
        "transient_processing_failure",
    ]
    assert all(
        item.redacted_diagnostic is not None
        and item.redacted_diagnostic.startswith("redacted:sha256:")
        for item in store.settlements
    )
    assert secret not in repr(result)
    assert secret not in repr(store.settlements)


@pytest.mark.parametrize(
    "classifier",
    (_ThrowingClassifier(), _InvalidClassifier()),
    ids=("throws", "invalid-result"),
)
def test_classifier_failure_falls_back_to_the_original_consumer_error(
    classifier: ConsumerErrorClassifier,
) -> None:
    store = _Store()
    subscription = _subscription()
    event = _event(1)
    consumer = _Consumer(
        subscription.consumer_id,
        {
            event.event_id: TransientEventProcessingError(
                "backend_unavailable",
                redacted_diagnostic="transient_backend",
            )
        },
    )
    fallback = LocalRuntimeDiagnosticFallback()
    runtime = _runtime(
        store,
        subscription,
        consumer,
        error_classifier=classifier,
        diagnostic_fallback=fallback,
    )
    store.claims.append(_claim(event, subscription))

    result = runtime.dispatch_batch(subscription.key, lease_owner="worker-1")

    assert result.retry_scheduled_count == 1
    assert result.dead_lettered_count == 0
    assert store.settlements[0].target_state is DeliveryState.RETRY_WAIT
    assert store.settlements[0].reason_class == "transient_processing_failure"
    diagnostic = fallback.snapshot()[0]
    assert diagnostic.category is RuntimeDiagnosticCategory.DELIVERY_CLASSIFIER_FAILURE
    assert (
        diagnostic.operation
        == RuntimeDiagnosticOperation.CONSUMER_ERROR_CLASSIFICATION.value
    )


def test_invalid_classifier_preserves_original_permanent_failure_kind() -> None:
    store = _Store()
    subscription = _subscription()
    event = _event(1)
    consumer = _Consumer(
        subscription.consumer_id,
        {
            event.event_id: PermanentEventProcessingError(
                "invalid_payload",
                redacted_diagnostic="schema_mismatch",
            )
        },
    )
    runtime = _runtime(
        store,
        subscription,
        consumer,
        error_classifier=_InvalidClassifier(),
    )
    store.claims.append(_claim(event, subscription))

    result = runtime.dispatch_batch(subscription.key, lease_owner="worker-1")

    assert result.dead_lettered_count == 1
    assert result.retry_scheduled_count == 0
    assert store.settlements[0].target_state is DeliveryState.DEAD_LETTER
    assert store.settlements[0].reason_class == "permanent_processing_failure"


def test_dead_letter_write_failure_is_isolated_and_never_retains_raw_message() -> None:
    secret = "secret-token-value"
    store = _Store()
    subscription = _subscription(retry_policy=RetryPolicy(max_attempts=1))
    failed = _event(1, stream_id="run:poison")
    healthy = _event(2, stream_id="run:healthy")
    consumer = _Consumer(
        subscription.consumer_id,
        {failed.event_id: RuntimeError(f"poison includes {secret}")},
    )
    runtime = _runtime(store, subscription, consumer)
    failed_claim = _claim(failed, subscription)
    healthy_claim = _claim(healthy, subscription)
    store.fail_settlement_ids.add(failed_claim.delivery.delivery_id)
    store.claims.extend([failed_claim, healthy_claim])

    result = runtime.dispatch_batch(subscription.key, lease_owner="worker-1")

    assert result.processing_failure_count == 1
    assert result.acknowledged_count == 1
    failure = result.attempts[0].failure
    assert failure is not None
    assert failure.phase is DeliveryFailurePhase.SETTLEMENT
    assert failure.reason_class == "delivery_settlement_failed"
    assert failure.redacted_diagnostic == "RuntimeError"
    assert secret not in repr(result)
    fallback_records = runtime.diagnostic_fallback.snapshot()
    assert len(fallback_records) == 1
    assert fallback_records[0].operation == "delivery_settlement"
    assert secret not in repr(fallback_records[0].to_dict())


def test_retry_lease_recovery_and_redelivery_all_require_effect_capability() -> None:
    store = _Store()
    gate = _CapabilityGate()
    subscription = _subscription(external=True, supports_repair=True)
    consumer = _Consumer(subscription.consumer_id)
    runtime = _runtime(store, subscription, consumer, gate=gate)

    retry_event = _event(1)
    store.claims.append(_claim(retry_event, subscription, attempt_count=2))
    runtime.dispatch_batch(subscription.key, lease_owner="worker-1")

    recovery_event = _event(2)
    store.claims.append(_claim(recovery_event, subscription, attempt_count=2))
    runtime.dispatch_batch(
        subscription.key,
        lease_owner="worker-1",
    )

    redelivery_event = _event(3)
    store.claims.append(
        _claim(
            redelivery_event,
            subscription,
            delivery_generation=2,
            attempt_count=2,
        )
    )
    runtime.dispatch_batch(
        subscription.key,
        lease_owner="worker-1",
    )

    assert AutomaticDeliveryOperation.RETRY in gate.required
    assert AutomaticDeliveryOperation.LEASE_RECOVERY in gate.required
    assert AutomaticDeliveryOperation.REDELIVERY in gate.required
    assert gate.required[-3:] == [
        AutomaticDeliveryOperation.REDELIVERY,
        AutomaticDeliveryOperation.RETRY,
        AutomaticDeliveryOperation.LEASE_RECOVERY,
    ]


def test_capability_failure_happens_before_claim_or_consumer_visibility() -> None:
    store = _Store()
    gate = _CapabilityGate()
    subscription = _subscription(external=True)
    consumer = _Consumer(subscription.consumer_id)
    runtime = _runtime(store, subscription, consumer, gate=gate)
    store.claims.append(_claim(_event(1), subscription))
    gate.fail_operations.add(AutomaticDeliveryOperation.INITIAL_DELIVERY)

    with pytest.raises(EventConsumerIdempotencyError, match="unavailable"):
        runtime.dispatch_batch(subscription.key, lease_owner="worker-1")

    assert store.last_claim_request is None
    assert consumer.calls == []


def test_paused_subscription_returns_empty_batch_without_claiming() -> None:
    store = _Store()
    subscription = replace(_subscription(), status=SubscriptionStatus.PAUSED)
    consumer = _Consumer(subscription.consumer_id)
    runtime = _runtime(store, subscription, consumer)
    store.claims.append(_claim(_event(1), subscription))

    result = runtime.dispatch_batch(subscription.key, lease_owner="worker-1")

    assert result.claimed_count == 0
    assert store.last_claim_request is None
    assert consumer.calls == []


def test_duplicate_store_claims_are_rejected_before_consumer_effects() -> None:
    store = _Store()
    subscription = _subscription()
    consumer = _Consumer(subscription.consumer_id)
    runtime = _runtime(store, subscription, consumer)
    duplicate = _claim(_event(1), subscription)
    store.claims.extend([duplicate, duplicate])

    result = runtime.dispatch_batch(subscription.key, lease_owner="worker-1")

    assert result.processing_failure_count == 2
    assert all(
        item.failure is not None
        and item.failure.reason_class == "duplicate_delivery_claim"
        for item in result.attempts
    )
    assert consumer.calls == []
    assert store.settlements == []


def test_resume_revalidates_external_effect_capability_before_activation() -> None:
    store = _Store()
    gate = _CapabilityGate()
    subscription = replace(
        _subscription(external=True),
        status=SubscriptionStatus.PAUSED,
    )
    consumer = _Consumer(subscription.consumer_id)
    runtime = _runtime(store, subscription, consumer, gate=gate)
    gate.fail_activation = True

    with pytest.raises(EventConsumerIdempotencyError, match="failed idempotency"):
        runtime.consumers.resume(subscription.key, reason="maintenance complete")

    assert store.subscriptions[subscription.key].status is SubscriptionStatus.PAUSED
    assert store.status_changes == []


def test_invalid_consumer_outcome_is_a_permanent_contract_failure() -> None:
    store = _Store()
    subscription = _subscription()
    event = _event(1)
    consumer = _Consumer(
        subscription.consumer_id,
        {event.event_id: {"status": "ack"}},
    )
    runtime = _runtime(store, subscription, consumer)
    store.claims.append(_claim(event, subscription))

    result = runtime.dispatch_batch(subscription.key, lease_owner="worker-1")

    assert result.dead_lettered_count == 1
    assert result.retry_scheduled_count == 0
    assert store.settlements[0].reason_class == "invalid_consumer_outcome"
    assert store.settlements[0].redacted_diagnostic is not None
    assert store.settlements[0].redacted_diagnostic.startswith("redacted:sha256:")
    assert "dict" not in store.settlements[0].redacted_diagnostic


def test_expired_legacy_lease_is_rejected_before_consumer_invocation() -> None:
    store = _Store()
    subscription = _subscription()
    consumer = _Consumer(subscription.consumer_id)
    runtime = _runtime(store, subscription, consumer)
    valid = _claim(_event(1), subscription)
    expired_at = NOW - timedelta(seconds=1)
    legacy_lease = replace(
        valid.lease,
        lease_expires_at=expired_at,
        lease_started_at=None,
    )
    store.claims.append(
        ClaimedDelivery(
            delivery=replace(valid.delivery, lease_expires_at=expired_at),
            event=valid.event,
            lease=legacy_lease,
        )
    )

    result = runtime.dispatch_batch(subscription.key, lease_owner="worker-1")

    assert result.processing_failure_count == 1
    assert result.attempts[0].failure is not None
    assert result.attempts[0].failure.phase is DeliveryFailurePhase.CLAIM_VALIDATION
    assert consumer.calls == []
    assert store.settlements == []


def test_claim_consumer_mismatch_fails_closed_but_other_claim_is_processed() -> None:
    store = _Store()
    subscription = _subscription()
    consumer = _Consumer(subscription.consumer_id)
    runtime = _runtime(store, subscription, consumer)
    bad = _claim(_event(1, stream_id="run:bad"), subscription)
    bad = ClaimedDelivery(
        delivery=replace(bad.delivery, consumer_id="wrong-consumer"),
        event=bad.event,
        lease=bad.lease,
    )
    healthy = _claim(_event(2, stream_id="run:healthy"), subscription)
    store.claims.extend([bad, healthy])

    result = runtime.dispatch_batch(subscription.key, lease_owner="worker-1")

    assert result.processing_failure_count == 1
    assert result.acknowledged_count == 1
    assert not result.attempts[0].consumer_called
    assert result.attempts[0].failure is not None
    assert result.attempts[0].failure.phase is DeliveryFailurePhase.CLAIM_VALIDATION
    assert len(consumer.calls) == 1


def test_claim_filter_mismatch_isolated_before_consumer_invocation() -> None:
    store = _Store()
    subscription = _subscription()
    consumer = _Consumer(subscription.consumer_id)
    runtime = _runtime(store, subscription, consumer)
    wrong_type = _claim(
        _event(1, stream_id="run:wrong-type", event_type="other.event"),
        subscription,
    )
    healthy = _claim(_event(2, stream_id="run:healthy"), subscription)
    store.claims.extend([wrong_type, healthy])

    result = runtime.dispatch_batch(subscription.key, lease_owner="worker-1")

    assert result.processing_failure_count == 1
    assert result.acknowledged_count == 1
    assert len(consumer.calls) == 1
    assert consumer.calls[0][0].event_id == healthy.event.event_id


def test_requeue_requires_out_of_order_contract_and_matching_dead_letter() -> None:
    store = _Store()
    gate = _CapabilityGate()
    subscription = _subscription(
        external=True,
        supports_repair=True,
        tenant_id="tenant-a",
    )
    consumer = _Consumer(subscription.consumer_id)
    runtime = _runtime(store, subscription, consumer, gate=gate)
    record = DeadLetterRecord(
        dead_letter_id="dead-letter-1",
        delivery_id="delivery-original",
        event_id="evt-delivery-1",
        stream_id="run:delivery-1",
        stream_sequence=1,
        subscription_id=subscription.subscription_id,
        subscription_version=subscription.subscription_version,
        consumer_id=subscription.consumer_id,
        consumer_effect_id=subscription.effect.consumer_effect_id,
        delivery_generation=1,
        attempt_count=5,
        first_failure_at=NOW - timedelta(minutes=5),
        last_failure_at=NOW - timedelta(minutes=1),
        reason_class="backend_unavailable",
        tenant_id="tenant-a",
        disposition=DeadLetterDisposition.OPEN,
    )
    store.dead_letters[record.dead_letter_id] = record
    action = DeadLetterAction(
        dead_letter_id=record.dead_letter_id,
        operator_id="operator-1",
        reason="backend repaired",
        requested_at=NOW,
        idempotency_ready=True,
    )

    delivery = runtime.requeue_dead_letter(subscription.key, action)

    assert delivery.delivery_generation == 2
    assert delivery.state is DeliveryState.PENDING
    assert gate.required[-1] is AutomaticDeliveryOperation.REQUEUE
    assert store.requeued == [action]

    unsafe = _subscription(version=2, external=True, supports_repair=False)
    unsafe_consumer = _Consumer(unsafe.consumer_id)
    runtime.register(unsafe, unsafe_consumer)
    with pytest.raises(
        EventConsumerIdempotencyError,
        match="new subscription version.*compensation workflow",
    ):
        runtime.requeue_dead_letter(unsafe.key, action)

    retired = replace(
        _subscription(
            version=3,
            external=True,
            supports_repair=True,
            tenant_id="tenant-a",
        ),
        status=SubscriptionStatus.RETIRED,
    )
    runtime.register(retired, _Consumer(retired.consumer_id))
    with pytest.raises(
        EventConsumerMismatchError,
        match="retired subscription",
    ):
        runtime.requeue_dead_letter(retired.key, action)
    assert store.requeued == [action]


def test_authorized_redelivery_requires_capability_before_store_mutation() -> None:
    trace: list[str] = []
    store = _Store(trace)
    gate = _CapabilityGate(trace)
    authorizer = _RedeliveryAuthorizer(trace=trace)
    subscription = _subscription(
        external=True,
        supports_repair=True,
        tenant_id="tenant-a",
    )
    runtime = _runtime(
        store,
        subscription,
        _Consumer(subscription.consumer_id),
        gate=gate,
        authorizer=authorizer,
    )
    trace.clear()
    request = RedeliveryRequest(
        redelivery_id="redelivery-1",
        subscription=subscription.key,
        source_stream_id="run:redelivery",
        from_sequence=1,
        through_sequence=1,
        requested_at=NOW,
        operator_id="operator-1",
        operator_reason="authorized repair",
        authorization_evidence_ref="authz-decision:redelivery-1",
        tenant_id="tenant-a",
    )

    report = runtime.begin_redelivery(request)

    assert report.redelivery_id == request.redelivery_id
    assert trace == ["authorize", "capability", "store"]
    assert authorizer.requests == [
        RedeliveryAuthorizationRequest.from_redelivery(request)
    ]
    assert gate.required[-1] is AutomaticDeliveryOperation.REDELIVERY
    assert store.redelivery_requests == [request]


def test_authorized_redelivery_poison_event_is_bounded_and_dead_letters_again() -> None:
    store = _Store()
    gate = _CapabilityGate()
    subscription = _subscription(
        external=True,
        supports_repair=True,
        tenant_id="tenant-a",
    )
    poison = _event(1, stream_id="run:redelivery", tenant_id="tenant-a")
    consumer = _Consumer(
        subscription.consumer_id,
        outcomes={
            poison.event_id: PermanentEventProcessingError("poison redelivery")
        },
    )
    runtime = _runtime(
        store,
        subscription,
        consumer,
        gate=gate,
        authorizer=_RedeliveryAuthorizer(),
    )
    request = RedeliveryRequest(
        redelivery_id="poison-redelivery",
        subscription=subscription.key,
        source_stream_id=poison.stream_id,
        from_sequence=poison.stream_sequence,
        through_sequence=poison.stream_sequence,
        requested_at=NOW,
        operator_id="operator-1",
        operator_reason="confirm repaired poison handling",
        authorization_evidence_ref="authz-decision:poison-redelivery",
        tenant_id="tenant-a",
    )

    report = runtime.begin_redelivery(request)
    claim = _claim(poison, subscription, delivery_generation=2)
    store.claims.append(claim)
    result = runtime.dispatch_batch(subscription.key, lease_owner="worker-1")

    assert report.items[0].delivery_generation == 2
    assert result.dead_lettered_count == 1
    assert result.attempts[0].state is DeliveryState.DEAD_LETTER
    assert result.attempts[0].delivery_generation == 2
    assert len(consumer.calls) == 1
    assert AutomaticDeliveryOperation.REDELIVERY in gate.required

    gate.fail_operations.add(AutomaticDeliveryOperation.REDELIVERY)
    with pytest.raises(EventConsumerIdempotencyError, match="capability"):
        runtime.begin_redelivery(replace(request, redelivery_id="redelivery-2"))
    assert store.redelivery_requests == [request]


def test_redelivery_fails_closed_without_an_authorizer_before_capability_or_store() -> None:
    trace: list[str] = []
    store = _Store(trace)
    gate = _CapabilityGate(trace)
    subscription = _subscription(
        external=True,
        supports_repair=True,
        tenant_id="tenant-a",
    )
    runtime = _runtime(
        store,
        subscription,
        _Consumer(subscription.consumer_id),
        gate=gate,
    )
    trace.clear()
    request = RedeliveryRequest(
        redelivery_id="missing-authorizer",
        subscription=subscription.key,
        source_stream_id="run:redelivery",
        from_sequence=1,
        through_sequence=1,
        requested_at=NOW,
        operator_id="operator-1",
        operator_reason="repair",
        authorization_evidence_ref="authz:missing-authorizer",
        tenant_id="tenant-a",
    )

    with pytest.raises(EventDeliveryConfigurationError, match="authorizer"):
        runtime.begin_redelivery(request)

    assert trace == []
    assert gate.required == []
    assert store.redelivery_requests == []


def test_redelivery_request_rejects_an_unbounded_explicit_range() -> None:
    with pytest.raises(ValueError, match="range cannot exceed"):
        RedeliveryRequest(
            redelivery_id="oversized-range",
            subscription=SubscriptionKey("repair", 1),
            source_stream_id="run:redelivery",
            from_sequence=1,
            through_sequence=MAX_REDELIVERY_ITEMS + 1,
            requested_at=NOW,
            operator_id="operator-1",
            operator_reason="repair",
            authorization_evidence_ref="authz:oversized-range",
            tenant_id="tenant-a",
        )


@pytest.mark.parametrize(
    "authorizer_case",
    ["denied", "error", "invalid", "tampered_request", "tampered_decision"],
)
def test_redelivery_rejects_untrusted_authorization_decisions_before_scope_lookup(
    authorizer_case: str,
) -> None:
    trace: list[str] = []
    store = _Store(trace)
    gate = _CapabilityGate(trace)
    subscription = _subscription(
        external=True,
        supports_repair=True,
        tenant_id="tenant-a",
    )
    request = RedeliveryRequest(
        redelivery_id=f"authorization-{authorizer_case}",
        subscription=subscription.key,
        source_stream_id="run:redelivery",
        from_sequence=1,
        through_sequence=1,
        requested_at=NOW,
        operator_id="operator-1",
        operator_reason="repair",
        authorization_evidence_ref=f"authz:{authorizer_case}",
        tenant_id="tenant-a",
    )
    if authorizer_case == "denied":
        authorizer = _RedeliveryAuthorizer(trace=trace, authorized=False)
        error_type = EventRedeliveryAuthorizationError
    elif authorizer_case == "error":
        authorizer = _RedeliveryAuthorizer(
            trace=trace,
            error=RuntimeError("secret authorization backend failure"),
        )
        error_type = EventRedeliveryAuthorizationError
    elif authorizer_case == "invalid":
        authorizer = _RedeliveryAuthorizer(
            trace=trace,
            invalid_response={"authorized": True},
        )
        error_type = EventRedeliveryAuthorizationContractError
    elif authorizer_case == "tampered_request":
        authorizer = _RedeliveryAuthorizer(
            trace=trace,
            tamper_request_checksum=True,
        )
        error_type = EventRedeliveryAuthorizationError
    else:
        authorizer = _RedeliveryAuthorizer(
            trace=trace,
            tamper_decision_checksum=True,
        )
        error_type = EventRedeliveryAuthorizationContractError
    runtime = _runtime(
        store,
        subscription,
        _Consumer(subscription.consumer_id),
        gate=gate,
        authorizer=authorizer,
    )
    trace.clear()

    with pytest.raises(error_type) as caught:
        runtime.begin_redelivery(request)

    assert trace == ["authorize"]
    assert gate.required == []
    assert store.redelivery_requests == []
    if authorizer_case == "error":
        assert "secret authorization backend failure" not in str(caught.value)
        assert caught.value.__cause__ is None


@pytest.mark.parametrize(
    "changed_fields",
    [
        {"redelivery_id": "different-redelivery"},
        {"subscription": SubscriptionKey("different-subscription", 2)},
        {"source_stream_id": "run:different"},
        {"from_sequence": 2, "through_sequence": 2},
        {"through_sequence": None},
        {"requested_at": NOW + timedelta(seconds=1)},
        {"operator_id": "different-operator"},
        {"operator_reason": "different reason"},
        {"authorization_evidence_ref": "authz:different"},
        {"tenant_id": "tenant-b"},
    ],
)
def test_redelivery_authorization_decision_binds_every_request_field(
    changed_fields: dict[str, object],
) -> None:
    trace: list[str] = []
    store = _Store(trace)
    gate = _CapabilityGate(trace)
    subscription = _subscription(
        external=True,
        supports_repair=True,
        tenant_id="tenant-a",
    )
    request = RedeliveryRequest(
        redelivery_id="field-binding",
        subscription=subscription.key,
        source_stream_id="run:redelivery",
        from_sequence=1,
        through_sequence=1,
        requested_at=NOW,
        operator_id="operator-1",
        operator_reason="repair",
        authorization_evidence_ref="authz:field-binding",
        tenant_id="tenant-a",
    )
    mismatched = replace(
        RedeliveryAuthorizationRequest.from_redelivery(request),
        **changed_fields,
    )
    runtime = _runtime(
        store,
        subscription,
        _Consumer(subscription.consumer_id),
        gate=gate,
        authorizer=_RedeliveryAuthorizer(trace=trace, bind_to=mismatched),
    )
    trace.clear()

    with pytest.raises(EventRedeliveryAuthorizationContractError, match="does not match"):
        runtime.begin_redelivery(request)

    assert trace == ["authorize"]
    assert gate.required == []
    assert store.redelivery_requests == []


def test_redelivery_authorization_precedes_subscription_existence_checks() -> None:
    store = _Store()
    gate = _CapabilityGate()
    subscription = _subscription(
        external=True,
        supports_repair=True,
        tenant_id="tenant-a",
    )
    request = RedeliveryRequest(
        redelivery_id="unknown-subscription",
        subscription=SubscriptionKey("unknown-subscription", 1),
        source_stream_id="run:redelivery",
        from_sequence=1,
        through_sequence=1,
        requested_at=NOW,
        operator_id="operator-1",
        operator_reason="repair",
        authorization_evidence_ref="authz:unknown-subscription",
        tenant_id="tenant-a",
    )
    denied = _runtime(
        store,
        subscription,
        _Consumer(subscription.consumer_id),
        gate=gate,
        authorizer=_RedeliveryAuthorizer(authorized=False),
    )

    with pytest.raises(EventRedeliveryAuthorizationError, match="denied"):
        denied.begin_redelivery(request)

    approved = DurableDeliveryRuntime(
        store,  # type: ignore[arg-type]
        consumers=denied.consumers,
        redelivery_authorizer=_RedeliveryAuthorizer(),
    )
    with pytest.raises(EventSubscriptionNotFoundError):
        approved.begin_redelivery(request)

    assert gate.required == []
    assert store.redelivery_requests == []


def test_redelivery_exact_retry_is_authorized_again_before_store_idempotence() -> None:
    trace: list[str] = []
    store = _Store(trace)
    gate = _CapabilityGate(trace)
    authorizer = _RedeliveryAuthorizer(trace=trace)
    subscription = _subscription(
        external=True,
        supports_repair=True,
        tenant_id="tenant-a",
    )
    runtime = _runtime(
        store,
        subscription,
        _Consumer(subscription.consumer_id),
        gate=gate,
        authorizer=authorizer,
    )
    trace.clear()
    request = RedeliveryRequest(
        redelivery_id="authorized-exact-retry",
        subscription=subscription.key,
        source_stream_id="run:redelivery",
        from_sequence=1,
        through_sequence=1,
        requested_at=NOW,
        operator_id="operator-1",
        operator_reason="repair",
        authorization_evidence_ref="authz:authorized-exact-retry",
        tenant_id="tenant-a",
    )

    runtime.begin_redelivery(request)
    runtime.begin_redelivery(request)

    assert trace == [
        "authorize",
        "capability",
        "store",
        "authorize",
        "capability",
        "store",
    ]
    assert len(authorizer.requests) == 2


def test_naive_clock_fails_before_claim() -> None:
    store = _Store()
    subscription = _subscription()
    consumer = _Consumer(subscription.consumer_id)
    runtime = DurableDeliveryRuntime(store, clock=_Clock(NOW.replace(tzinfo=None)))  # type: ignore[arg-type]

    with pytest.raises(EventDeliveryConfigurationError, match="timezone-aware"):
        runtime.register(subscription, consumer)
        runtime.dispatch_batch(subscription.key, lease_owner="worker-1")

    assert store.last_claim_request is None


def test_clock_failure_isolated_per_claim_and_batch_continues() -> None:
    secret = "clock-secret-must-not-leak"
    store = _Store()
    subscription = _subscription()
    consumer = _Consumer(subscription.consumer_id)
    clock = _SequenceClock(
        [
            NOW,
            RuntimeError(secret),
            NOW,
            RuntimeError(secret),
        ]
    )
    runtime = _runtime(
        store,
        subscription,
        consumer,
        clock=clock,
    )
    failed = _claim(_event(1, stream_id="run:clock-failed"), subscription)
    healthy = _claim(_event(2, stream_id="run:clock-healthy"), subscription)
    store.claims.extend([failed, healthy])

    result = runtime.dispatch_batch(subscription.key, lease_owner="worker-1")

    assert result.processing_failure_count == 1
    assert result.acknowledged_count == 1
    assert result.attempts[0].failure is not None
    assert result.attempts[0].failure.phase is DeliveryFailurePhase.CLOCK
    assert len(consumer.calls) == 1
    assert consumer.calls[0][0].event_id == healthy.event.event_id
    assert secret not in repr(result)


def test_public_runtime_failures_strip_secret_exception_context() -> None:
    secret = "driver-secret-that-must-not-leak"
    subscription = _subscription()
    consumer = _Consumer(subscription.consumer_id)

    clock_runtime = DurableDeliveryRuntime(
        _Store(),  # type: ignore[arg-type]
        clock=_SequenceClock([RuntimeError(secret)]),
    )
    clock_runtime.register(subscription, consumer)
    with pytest.raises(EventDeliveryConfigurationError) as clock_error:
        clock_runtime.dispatch_batch(subscription.key, lease_owner="worker-1")
    assert clock_error.value.__cause__ is None
    assert clock_error.value.__context__ is None
    assert secret not in "".join(traceback.format_exception(clock_error.value))

    store = _Store()
    runtime = _runtime(store, subscription, consumer)
    store.claim_error = RuntimeError(secret)
    with pytest.raises(EventDeliveryStoreOperationError) as store_error:
        runtime.dispatch_batch(subscription.key, lease_owner="worker-1")
    assert store_error.value.__cause__ is None
    assert store_error.value.__context__ is None
    assert secret not in "".join(traceback.format_exception(store_error.value))


def test_durable_delivery_runtime_symbols_are_publicly_exported() -> None:
    from framework.events import (  # noqa: PLC0415
        DeliveryBatchResult,
        DurableConsumerRegistry,
        DurableDeliveryRuntime,
        EventConsumerMismatchError,
        EventDeliveryContractError,
    )
    from framework.events.runtime import (  # noqa: PLC0415
        DeliveryBatchResult as RuntimeDeliveryBatchResult,
    )

    assert DeliveryBatchResult is RuntimeDeliveryBatchResult
    assert DurableConsumerRegistry is not None
    assert DurableDeliveryRuntime is not None
    assert EventConsumerMismatchError is not None
    assert EventDeliveryContractError is not None
