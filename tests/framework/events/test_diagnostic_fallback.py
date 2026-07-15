from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields, replace
from datetime import UTC, datetime
from threading import Lock
from types import SimpleNamespace

import pytest

from framework.events.canonical import BusinessContext, ProducerIdentity, StoredEvent
from framework.events.errors import EventContractError
from framework.events.runtime.delivery import (
    DurableDeliveryRuntime,
    EventConsumerMismatchError,
    EventDeliveryContractError,
    EventDeliveryStoreOperationError,
)
from framework.events.runtime.fallback import (
    LocalRuntimeDiagnosticFallback,
    RuntimeDiagnosticCategory,
    RuntimeDiagnosticComponent,
    RuntimeDiagnosticOperation,
)
from framework.events.runtime.models import (
    ConsumerEffectContract,
    DeadLetterAction,
    DeadLetterDisposition,
    DeadLetterRecord,
    DurableSubscription,
    SubscriptionFilter,
    SubscriptionStart,
    SubscriptionStartPolicy,
)
from framework.events.runtime.publisher import EventPublishRequest, EventRuntime
from framework.events.runtime.replay_engine import (
    DeterministicReplayEngine,
    ReplayCheckpoint,
    ReplayCoreError,
    ReplayHistoryOrderError,
    ReplaySourceReadError,
)
from framework.events.schema import EventSchemaCatalog, EventSchemaRegistration
from framework.events.subscriber import ConsumerOutcome
from tests.framework.events.test_deterministic_replay_engine import (
    _FakeReplayStore,
    _catalog as _replay_catalog,
    _event as _replay_event,
    _registry as _replay_registry,
    _request as _replay_request,
)
from tests.framework.events.test_durable_delivery_runtime import (
    _Consumer as _DeliveryConsumer,
    _Store as _DeliveryStore,
    _subscription as _delivery_subscription,
)
from framework.events.runtime.models import ReplayMode


NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
_FORBIDDEN_RECORD_KEYS = {
    "diagnostic",
    "dsn",
    "error",
    "event_id",
    "exception",
    "message",
    "payload",
    "run_id",
    "secret",
    "tenant_id",
    "trace_id",
}


class _SecretFailure(RuntimeError):
    pass


def _secret_error(secret: str) -> Exception:
    try:
        try:
            raise ValueError(f"postgresql://user:{secret}@db/news?token={secret}")
        except ValueError as cause:
            raise _SecretFailure(
                f"payload={{'authorization': 'Bearer {secret}'}}"
            ) from cause
    except Exception as error:
        return error


def _record(
    fallback: LocalRuntimeDiagnosticFallback,
    error: Exception,
    *,
    operation: RuntimeDiagnosticOperation = RuntimeDiagnosticOperation.PUBLISH,
) -> None:
    fallback.record(
        category=RuntimeDiagnosticCategory.EVENT_STORE_FAILURE,
        component=RuntimeDiagnosticComponent.EVENT_PUBLISHER,
        operation=operation,
        error=error,
    )


def _assert_safe_snapshot(
    fallback: LocalRuntimeDiagnosticFallback,
    secret: str,
) -> None:
    rendered = repr(tuple(item.to_dict() for item in fallback.snapshot()))
    assert secret not in rendered
    for diagnostic in fallback.snapshot():
        assert set(diagnostic.to_dict()) == {
            "category",
            "component",
            "operation",
            "occurred_at",
            "fingerprint",
        }
        assert _FORBIDDEN_RECORD_KEYS.isdisjoint(diagnostic.to_dict())
        assert diagnostic.fingerprint.startswith("sha256:")
        assert len(diagnostic.fingerprint) == 71


def test_fallback_is_bounded_and_evicted_deduplication_keys_can_reenter() -> None:
    fallback = LocalRuntimeDiagnosticFallback(capacity=3)
    first = _secret_error("first-secret")

    _record(fallback, first)
    first_fingerprint = fallback.snapshot()[0].fingerprint
    for number in range(1, 6):
        _record(
            fallback,
            type(f"Failure{number}", (RuntimeError,), {})("ignored-message"),
        )

    assert len(fallback) == fallback.capacity == 3
    assert first_fingerprint not in {
        diagnostic.fingerprint for diagnostic in fallback.snapshot()
    }

    _record(fallback, first)

    assert len(fallback) == 3
    assert fallback.snapshot()[-1].fingerprint == first_fingerprint


def test_concurrent_identical_failures_emit_exactly_once() -> None:
    sink_records = []
    telemetry_records = []
    sink_lock = Lock()

    def sink(diagnostic) -> None:
        with sink_lock:
            sink_records.append(diagnostic)

    def telemetry(diagnostic) -> None:
        with sink_lock:
            telemetry_records.append(diagnostic)

    fallback = LocalRuntimeDiagnosticFallback(
        capacity=8,
        sink=sink,
        telemetry_counter=telemetry,
    )

    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = [
            executor.submit(_record, fallback, RuntimeError(f"secret-{number}"))
            for number in range(256)
        ]
        for future in futures:
            future.result()

    assert len(fallback) == 1
    assert len(sink_records) == 1
    assert len(telemetry_records) == 1


def test_sink_and_telemetry_failures_are_local_only_and_nonrecursive() -> None:
    secret = "sink-secret-never-recorded"
    sink_calls = 0
    telemetry_calls = 0
    fallback: LocalRuntimeDiagnosticFallback

    def sink(_diagnostic) -> None:
        nonlocal sink_calls
        sink_calls += 1
        # A sink attempting to recurse is ignored by the thread-local guard.
        _record(
            fallback,
            RuntimeError(secret),
            operation=RuntimeDiagnosticOperation.DEAD_LETTER_REQUEUE,
        )
        raise RuntimeError(secret)

    def telemetry(_diagnostic) -> None:
        nonlocal telemetry_calls
        telemetry_calls += 1
        raise RuntimeError(secret)

    fallback = LocalRuntimeDiagnosticFallback(
        capacity=8,
        sink=sink,
        telemetry_counter=telemetry,
    )

    _record(fallback, _secret_error(secret))
    _record(fallback, _secret_error(secret))

    assert sink_calls == 1
    assert telemetry_calls == 1
    assert [item.category for item in fallback.snapshot()] == [
        RuntimeDiagnosticCategory.EVENT_STORE_FAILURE,
        RuntimeDiagnosticCategory.DIAGNOSTIC_SINK_FAILURE,
        RuntimeDiagnosticCategory.TELEMETRY_FAILURE,
    ]
    _assert_safe_snapshot(fallback, secret)


@pytest.mark.parametrize(
    ("capacity", "expected_categories"),
    [
        (1, [RuntimeDiagnosticCategory.EVENT_STORE_FAILURE]),
        (
            2,
            [
                RuntimeDiagnosticCategory.EVENT_STORE_FAILURE,
                RuntimeDiagnosticCategory.DIAGNOSTIC_SINK_FAILURE,
            ],
        ),
    ],
)
def test_callback_failures_never_evict_originating_diagnostic(
    capacity: int,
    expected_categories: list[RuntimeDiagnosticCategory],
) -> None:
    def fail(_diagnostic) -> None:
        raise RuntimeError("callback-secret")

    fallback = LocalRuntimeDiagnosticFallback(
        capacity=capacity,
        sink=fail,
        telemetry_counter=fail,
    )

    _record(fallback, RuntimeError("store-secret"))

    assert [item.category for item in fallback.snapshot()] == expected_categories
    assert fallback.snapshot()[0].operation == "publish"


@pytest.mark.parametrize(
    ("component", "operation"),
    [
        ("tenant_acme", RuntimeDiagnosticOperation.PUBLISH),
        (RuntimeDiagnosticComponent.EVENT_PUBLISHER, "run_123"),
        ("event_evt_secret", RuntimeDiagnosticOperation.PUBLISH),
        (RuntimeDiagnosticComponent.EVENT_PUBLISHER, "trace_deadbeef"),
    ],
)
def test_unknown_diagnostic_labels_fail_closed_before_callbacks(
    component: object,
    operation: object,
) -> None:
    callbacks = []
    fallback = LocalRuntimeDiagnosticFallback(
        capacity=4,
        sink=callbacks.append,
        telemetry_counter=callbacks.append,
    )

    recorded = fallback.record(
        category=RuntimeDiagnosticCategory.EVENT_STORE_FAILURE,
        component=component,  # type: ignore[arg-type]
        operation=operation,  # type: ignore[arg-type]
        error=RuntimeError("secret"),
    )

    assert recorded is None
    assert fallback.snapshot() == ()
    assert callbacks == []


def test_process_control_exception_is_not_swallowed_and_guard_is_cleared() -> None:
    calls = 0

    def interrupt(_diagnostic) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise KeyboardInterrupt

    fallback = LocalRuntimeDiagnosticFallback(capacity=4, sink=interrupt)

    with pytest.raises(KeyboardInterrupt):
        _record(fallback, RuntimeError("first"))
    _record(
        fallback,
        LookupError("second"),
        operation=RuntimeDiagnosticOperation.SUBSCRIPTION_LOOKUP,
    )

    assert calls == 2
    assert [item.operation for item in fallback.snapshot()] == [
        "publish",
        "subscription_lookup",
    ]


def test_thread_local_reentrancy_guard_is_cleared_and_does_not_cross_threads() -> None:
    calls = 0

    def fail_once(_diagnostic) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("first sink failure")

    fallback = LocalRuntimeDiagnosticFallback(capacity=8, sink=fail_once)
    _record(fallback, RuntimeError("first"))
    _record(
        fallback,
        LookupError("second"),
        operation=RuntimeDiagnosticOperation.SUBSCRIPTION_LOOKUP,
    )
    thread_operations = (
        RuntimeDiagnosticOperation.DELIVERY_CLAIM,
        RuntimeDiagnosticOperation.DEAD_LETTER_LOOKUP,
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        tuple(
            executor.map(
                lambda operation: _record(
                    fallback,
                    OSError(operation.value),
                    operation=operation,
                ),
                thread_operations,
            )
        )

    assert calls == 4
    assert {item.operation for item in fallback.snapshot()} >= {
        "publish",
        "subscription_lookup",
        "delivery_claim",
        "dead_letter_lookup",
    }


class _FailingPublisherStore:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    def unit_of_work(self):
        self.calls += 1
        raise self.error


class _InvalidAppendResultUnitOfWork:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def append_event(self, event):
        return SimpleNamespace(
            event=StoredEvent(
                candidate=event,
                observed_at=NOW,
                stream_sequence=1,
            )
        )

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        del exc, traceback
        if exc_type is not None or self.commits == 0:
            self.rollback()
        return False


class _InvalidAppendResultStore:
    def __init__(self) -> None:
        self.transaction = _InvalidAppendResultUnitOfWork()

    def unit_of_work(self):
        return self.transaction


def _publisher_catalog() -> EventSchemaCatalog:
    catalog = EventSchemaCatalog()
    catalog.register(
        EventSchemaRegistration(
            event_type="io.newsroom.test.fallback",
            data_schema="io.newsroom.test.fallback/v1",
            json_schema={
                "type": "object",
                "properties": {"value": {"type": "integer"}},
                "required": ["value"],
                "additionalProperties": False,
            },
            current=True,
        )
    )
    return catalog


def _publish_request() -> EventPublishRequest:
    return EventPublishRequest(
        event_id="evt-secret-identity",
        event_type="io.newsroom.test.fallback",
        data_schema="io.newsroom.test.fallback/v1",
        source="tests.diagnostic_fallback",
        occurred_at=NOW,
        stream_id="run:secret-run",
        business_context=BusinessContext(run_id="secret-run"),
        producer=ProducerIdentity(component="diagnostic-test", version="1"),
        tenant_id="secret-tenant",
        payload={"value": 1},
    )


def test_publish_store_outage_records_once_and_preserves_original_exception() -> None:
    secret = "publisher-store-password"
    error = _secret_error(secret)
    store = _FailingPublisherStore(error)
    fallback = LocalRuntimeDiagnosticFallback(capacity=4)
    runtime = EventRuntime(
        store=store,  # type: ignore[arg-type]
        schema_catalog=_publisher_catalog(),
        diagnostic_fallback=fallback,
    )

    for _ in range(2):
        with pytest.raises(_SecretFailure) as caught:
            runtime.publish(_publish_request())
        assert caught.value is error

    assert store.calls == 2
    assert len(fallback) == 1
    assert (
        fallback.snapshot()[0].category
        is RuntimeDiagnosticCategory.EVENT_STORE_FAILURE
    )
    assert fallback.snapshot()[0].operation == "publish"
    _assert_safe_snapshot(fallback, secret)


def test_publish_invalid_append_result_records_fallback_and_rolls_back() -> None:
    store = _InvalidAppendResultStore()
    fallback = LocalRuntimeDiagnosticFallback(capacity=4)
    runtime = EventRuntime(
        store=store,  # type: ignore[arg-type]
        schema_catalog=_publisher_catalog(),
        diagnostic_fallback=fallback,
    )

    with pytest.raises(EventContractError, match="invalid append result"):
        runtime.publish(_publish_request())

    assert store.transaction.commits == 0
    assert store.transaction.rollbacks == 1
    assert [item.operation for item in fallback.snapshot()] == ["publish"]


class _Consumer:
    consumer_id = "diagnostic-consumer"

    def consume(self, event, context) -> ConsumerOutcome:
        del event, context
        return ConsumerOutcome.ack()


class _FailingDeliveryStore:
    def __init__(self, subscription: DurableSubscription, error: Exception) -> None:
        self.subscription = subscription
        self.error = error
        self.claim_calls = 0

    def register_subscription(self, subscription):
        return subscription

    def get_subscription(self, key):
        return self.subscription if key == self.subscription.key else None

    def claim_deliveries(self, request):
        del request
        self.claim_calls += 1
        raise self.error


def _subscription() -> DurableSubscription:
    return DurableSubscription(
        subscription_id="diagnostic-subscription",
        subscription_version=1,
        consumer_id="diagnostic-consumer",
        event_filter=SubscriptionFilter(),
        start=SubscriptionStart(SubscriptionStartPolicy.EARLIEST),
        effect=ConsumerEffectContract(),
    )


def test_delivery_claim_outage_records_once_without_changing_typed_failure() -> None:
    secret = "delivery-store-secret"
    error = _secret_error(secret)
    subscription = _subscription()
    store = _FailingDeliveryStore(subscription, error)
    fallback = LocalRuntimeDiagnosticFallback(capacity=4)
    runtime = DurableDeliveryRuntime(
        store,  # type: ignore[arg-type]
        diagnostic_fallback=fallback,
        clock=lambda: NOW,
    )
    runtime.register(subscription, _Consumer())

    for _ in range(2):
        with pytest.raises(EventDeliveryStoreOperationError) as caught:
            runtime.dispatch_batch(subscription.key, lease_owner="worker-1")
        assert caught.value.__cause__ is None
        assert caught.value.__context__ is None

    assert store.claim_calls == 2
    assert len(fallback) == 1
    assert fallback.snapshot()[0].operation == "delivery_claim"
    _assert_safe_snapshot(fallback, secret)


def _registered_delivery_runtime(
    store: _DeliveryStore,
    fallback: LocalRuntimeDiagnosticFallback,
    *,
    subscription: DurableSubscription | None = None,
) -> tuple[DurableDeliveryRuntime, DurableSubscription, _DeliveryConsumer]:
    selected = subscription or _delivery_subscription()
    consumer = _DeliveryConsumer(selected.consumer_id)
    runtime = DurableDeliveryRuntime(
        store,  # type: ignore[arg-type]
        diagnostic_fallback=fallback,
        clock=lambda: NOW,
    )
    runtime.register(selected, consumer)
    return runtime, selected, consumer


def _dead_letter(subscription: DurableSubscription) -> DeadLetterRecord:
    return DeadLetterRecord(
        dead_letter_id="dead-letter-invalid-response",
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
        first_failure_at=NOW,
        last_failure_at=NOW,
        reason_class="backend_unavailable",
        tenant_id=subscription.tenant_id,
        disposition=DeadLetterDisposition.OPEN,
    )


def _dead_letter_action(record: DeadLetterRecord) -> DeadLetterAction:
    return DeadLetterAction(
        dead_letter_id=record.dead_letter_id,
        operator_id="operator-1",
        reason="backend repaired",
        requested_at=NOW,
        idempotency_ready=True,
    )


def test_invalid_subscription_registration_response_records_fallback() -> None:
    store = _DeliveryStore()
    store.register_subscription = lambda _subscription: object()  # type: ignore[method-assign]
    fallback = LocalRuntimeDiagnosticFallback(capacity=8)
    subscription = _delivery_subscription()
    runtime = DurableDeliveryRuntime(
        store,  # type: ignore[arg-type]
        diagnostic_fallback=fallback,
        clock=lambda: NOW,
    )

    with pytest.raises(EventDeliveryContractError):
        runtime.register(subscription, _DeliveryConsumer(subscription.consumer_id))

    assert [item.operation for item in fallback.snapshot()] == [
        "subscription_registration"
    ]


def test_invalid_subscription_lookup_and_status_responses_record_fallback() -> None:
    store = _DeliveryStore()
    fallback = LocalRuntimeDiagnosticFallback(capacity=8)
    runtime, subscription, _consumer = _registered_delivery_runtime(store, fallback)

    store.get_subscription = lambda _key: object()  # type: ignore[method-assign]
    with pytest.raises(EventDeliveryContractError):
        runtime.consumers.resolve(subscription.key)
    store.get_subscription = (  # type: ignore[method-assign]
        lambda key: store.subscriptions.get(key)
    )
    store.set_subscription_status = (  # type: ignore[method-assign]
        lambda *_args, **_kwargs: object()
    )
    with pytest.raises(EventDeliveryContractError):
        runtime.consumers.pause(subscription.key, reason="maintenance")

    assert [item.operation for item in fallback.snapshot()] == [
        "subscription_lookup",
        "subscription_status_update",
    ]


def test_invalid_claim_response_records_fallback_and_preserves_contract_error() -> None:
    store = _DeliveryStore()
    fallback = LocalRuntimeDiagnosticFallback(capacity=8)
    runtime, subscription, _consumer = _registered_delivery_runtime(store, fallback)
    store.claim_deliveries = lambda _request: (object(),)  # type: ignore[method-assign]

    with pytest.raises(EventDeliveryContractError):
        runtime.dispatch_batch(subscription.key, lease_owner="worker-1")

    assert [item.operation for item in fallback.snapshot()] == ["delivery_claim"]


@pytest.mark.parametrize("surface", ["lookup", "requeue"])
def test_invalid_dead_letter_store_response_records_fallback(surface: str) -> None:
    store = _DeliveryStore()
    fallback = LocalRuntimeDiagnosticFallback(capacity=8)
    subscription = _delivery_subscription(supports_repair=True, tenant_id="tenant-a")
    runtime, subscription, _consumer = _registered_delivery_runtime(
        store,
        fallback,
        subscription=subscription,
    )
    record = _dead_letter(subscription)
    store.dead_letters[record.dead_letter_id] = record
    action = _dead_letter_action(record)
    if surface == "lookup":
        store.get_dead_letter = (  # type: ignore[method-assign]
            lambda *_args, **_kwargs: object()
        )
        expected_operation = "dead_letter_lookup"
    else:
        store.requeue_dead_letter = (  # type: ignore[method-assign]
            lambda _action: object()
        )
        expected_operation = "dead_letter_requeue"

    with pytest.raises(EventDeliveryContractError):
        runtime.requeue_dead_letter(subscription.key, action)

    assert [item.operation for item in fallback.snapshot()] == [expected_operation]


def test_delivery_domain_mismatches_do_not_emit_store_failure() -> None:
    store = _DeliveryStore()
    fallback = LocalRuntimeDiagnosticFallback(capacity=8)
    subscription = _delivery_subscription(supports_repair=True, tenant_id="tenant-a")
    runtime, subscription, consumer = _registered_delivery_runtime(
        store,
        fallback,
        subscription=subscription,
    )
    conflicting = replace(
        subscription,
        event_filter=SubscriptionFilter(
            event_types=frozenset({"io.newsroom.test.other"})
        ),
    )

    with pytest.raises(EventConsumerMismatchError):
        runtime.register(conflicting, consumer)
    assert fallback.snapshot() == ()

    record = replace(_dead_letter(subscription), subscription_id="other-subscription")
    store.dead_letters[record.dead_letter_id] = record
    with pytest.raises(EventConsumerMismatchError):
        runtime.requeue_dead_letter(subscription.key, _dead_letter_action(record))

    assert fallback.snapshot() == ()


def _replay_engine(
    store: _FakeReplayStore,
    fallback: LocalRuntimeDiagnosticFallback,
) -> DeterministicReplayEngine:
    return DeterministicReplayEngine(
        store,  # type: ignore[arg-type]
        _replay_catalog(),
        _replay_registry(),
        store.checkpoints,
        runtime_version="19.0.0",
        schema_catalog_version="counter-catalog/2",
        clock=lambda: NOW,
        page_size=1,
        diagnostic_fallback=fallback,
    )


@pytest.mark.parametrize(
    ("failure", "expected_category", "expected_operation"),
    [
        (
            "report",
            RuntimeDiagnosticCategory.REPLAY_REPORT_FAILURE,
            "replay_begin_failed",
        ),
        (
            "checkpoint",
            RuntimeDiagnosticCategory.REPLAY_CHECKPOINT_FAILURE,
            "replay_checkpoint_write_failed",
        ),
        (
            "source",
            RuntimeDiagnosticCategory.REPLAY_STORE_FAILURE,
            "source_read_failed",
        ),
        (
            "quarantine",
            RuntimeDiagnosticCategory.REPLAY_QUARANTINE_FAILURE,
            "quarantine_write",
        ),
    ],
)
def test_replay_store_boundaries_record_one_safe_fallback(
    failure: str,
    expected_category: RuntimeDiagnosticCategory,
    expected_operation: str,
) -> None:
    secret = "replay-dsn-password"
    store = _FakeReplayStore(
        [
            _replay_event(
                1,
                data_schema=(
                    "io.newsroom.counter/v99"
                    if failure == "quarantine"
                    else "io.newsroom.counter/v2"
                ),
            )
        ]
    )
    store.secret = secret
    if failure == "report":
        store.fail_begin = True
    elif failure == "checkpoint":
        store.checkpoints.secret = secret
        store.checkpoints.fail_writes = True
    elif failure == "source":
        store.fail_after_reads = 0
    else:
        store.fail_quarantine = True
    fallback = LocalRuntimeDiagnosticFallback(capacity=8)

    with pytest.raises(ReplaySourceReadError):
        _replay_engine(store, fallback).verify_history(
            _replay_request(f"fallback-{failure}", ReplayMode.VERIFY_HISTORY)
        )

    matching = [
        item
        for item in fallback.snapshot()
        if item.category is expected_category and item.operation == expected_operation
    ]
    assert len(matching) == 1
    _assert_safe_snapshot(fallback, secret)


def test_invalid_replay_begin_report_records_fallback_and_preserves_error() -> None:
    store = _FakeReplayStore([_replay_event(1)])
    original_begin = store.begin_replay

    def invalid_begin(request):
        return replace(original_begin(request), replay_id="different-replay")

    store.begin_replay = invalid_begin  # type: ignore[method-assign]
    fallback = LocalRuntimeDiagnosticFallback(capacity=8)

    with pytest.raises(ReplayCoreError):
        _replay_engine(store, fallback).verify_history(
            _replay_request("invalid-begin-report", ReplayMode.VERIFY_HISTORY)
        )

    assert [item.operation for item in fallback.snapshot()] == [
        "replay_begin_report_invalid"
    ]


def test_non_report_replay_begin_response_records_fallback() -> None:
    store = _FakeReplayStore([_replay_event(1)])
    store.begin_replay = lambda _request: object()  # type: ignore[method-assign]
    fallback = LocalRuntimeDiagnosticFallback(capacity=8)

    with pytest.raises(ReplayCoreError, match="invalid report"):
        _replay_engine(store, fallback).verify_history(
            _replay_request("non-report-begin-response", ReplayMode.VERIFY_HISTORY)
        )

    assert [item.operation for item in fallback.snapshot()] == [
        "replay_begin_report_invalid"
    ]


def test_invalid_replay_report_update_records_safe_typed_failure() -> None:
    store = _FakeReplayStore([_replay_event(1)])
    original_update = store.update_replay_report

    def invalid_update(report):
        return replace(original_update(report), replay_id="different-replay")

    store.update_replay_report = invalid_update  # type: ignore[method-assign]
    fallback = LocalRuntimeDiagnosticFallback(capacity=8)

    with pytest.raises(ReplaySourceReadError) as caught:
        _replay_engine(store, fallback).verify_history(
            _replay_request("invalid-report-update", ReplayMode.VERIFY_HISTORY)
        )

    assert caught.value.reason_class == "replay_report_update_invalid"
    assert [item.operation for item in fallback.snapshot()] == [
        "replay_report_update_invalid"
    ]


def test_invalid_replay_source_page_records_fallback_and_preserves_error() -> None:
    store = _FakeReplayStore([_replay_event(1)])
    original_read = store.read_stream

    def invalid_read(request):
        page = original_read(request)
        assert page.high_watermark is not None
        return replace(page, high_watermark=page.high_watermark + 1)

    store.read_stream = invalid_read  # type: ignore[method-assign]
    fallback = LocalRuntimeDiagnosticFallback(capacity=8)

    with pytest.raises(ReplayHistoryOrderError):
        _replay_engine(store, fallback).verify_history(
            _replay_request("invalid-source-page", ReplayMode.VERIFY_HISTORY)
        )

    assert [item.operation for item in fallback.snapshot()] == ["source_read_invalid"]


def test_non_page_replay_source_response_records_fallback() -> None:
    store = _FakeReplayStore([_replay_event(1)])
    store.read_stream = lambda _request: object()  # type: ignore[method-assign]
    fallback = LocalRuntimeDiagnosticFallback(capacity=8)

    with pytest.raises(AttributeError):
        _replay_engine(store, fallback).verify_history(
            _replay_request("non-page-source-response", ReplayMode.VERIFY_HISTORY)
        )

    assert [item.operation for item in fallback.snapshot()] == ["source_read_invalid"]


@pytest.mark.parametrize("checkpoint_surface", ["read", "write"])
def test_invalid_replay_checkpoint_response_records_fallback(
    checkpoint_surface: str,
) -> None:
    store = _FakeReplayStore([_replay_event(1)])
    if checkpoint_surface == "read":
        store.checkpoints.get_checkpoint = (  # type: ignore[method-assign]
            lambda *_args, **_kwargs: object()
        )
        expected_operation = "replay_checkpoint_read_invalid"
    else:
        store.checkpoints.save_checkpoint = (  # type: ignore[method-assign]
            lambda _checkpoint: object()
        )
        expected_operation = "replay_checkpoint_write_invalid"
    fallback = LocalRuntimeDiagnosticFallback(capacity=8)

    with pytest.raises(ReplaySourceReadError):
        _replay_engine(store, fallback).verify_history(
            _replay_request(
                f"invalid-checkpoint-{checkpoint_surface}",
                ReplayMode.VERIFY_HISTORY,
            )
        )

    assert [item.operation for item in fallback.snapshot()] == [expected_operation]


class _ExplodingReplayCheckpoint(ReplayCheckpoint):
    def verify_integrity(self) -> None:
        raise RuntimeError("checkpoint-proxy-secret")


def test_checkpoint_validation_exception_records_safe_typed_failure() -> None:
    store = _FakeReplayStore([_replay_event(1)])

    def invalid_save(checkpoint: ReplayCheckpoint) -> ReplayCheckpoint:
        values = {
            item.name: getattr(checkpoint, item.name)
            for item in fields(ReplayCheckpoint)
            if item.init
        }
        return _ExplodingReplayCheckpoint(**values)

    store.checkpoints.save_checkpoint = invalid_save  # type: ignore[method-assign]
    fallback = LocalRuntimeDiagnosticFallback(capacity=8)

    with pytest.raises(ReplaySourceReadError) as caught:
        _replay_engine(store, fallback).verify_history(
            _replay_request("checkpoint-validation-error", ReplayMode.VERIFY_HISTORY)
        )

    assert caught.value.reason_class == "replay_checkpoint_write_invalid"
    assert [item.operation for item in fallback.snapshot()] == [
        "replay_checkpoint_write_invalid"
    ]
    assert "checkpoint-proxy-secret" not in repr(
        tuple(item.to_dict() for item in fallback.snapshot())
    )


@pytest.mark.parametrize(
    ("quarantine_response", "error_type"),
    [(None, AssertionError), (object(), AttributeError)],
)
def test_invalid_quarantine_response_records_fallback_and_preserves_error(
    quarantine_response: object,
    error_type: type[Exception],
) -> None:
    store = _FakeReplayStore(
        [_replay_event(1, data_schema="io.newsroom.counter/v99")]
    )
    store.save_quarantine = (  # type: ignore[method-assign]
        lambda _record: quarantine_response
    )
    fallback = LocalRuntimeDiagnosticFallback(capacity=8)

    with pytest.raises(error_type):
        _replay_engine(store, fallback).verify_history(
            _replay_request("invalid-quarantine", ReplayMode.VERIFY_HISTORY)
        )

    assert [item.operation for item in fallback.snapshot()] == ["quarantine_write"]


def test_fallback_symbols_are_publicly_exported() -> None:
    from framework.events import (  # noqa: PLC0415
        LocalRuntimeDiagnosticFallback as PublicFallback,
        RuntimeDiagnosticComponent as PublicComponent,
        RuntimeDiagnosticOperation as PublicOperation,
    )
    from framework.events.runtime import (  # noqa: PLC0415
        LocalRuntimeDiagnosticFallback as RuntimeFallback,
        RuntimeDiagnosticComponent as RuntimeComponent,
        RuntimeDiagnosticOperation as RuntimeOperation,
    )

    assert PublicFallback is RuntimeFallback is LocalRuntimeDiagnosticFallback
    assert PublicComponent is RuntimeComponent is RuntimeDiagnosticComponent
    assert PublicOperation is RuntimeOperation is RuntimeDiagnosticOperation


def test_runtime_defaults_do_not_share_cross_tenant_fallback_state() -> None:
    first = EventRuntime(
        store=_FailingPublisherStore(RuntimeError("first")),  # type: ignore[arg-type]
        schema_catalog=_publisher_catalog(),
    )
    second = EventRuntime(
        store=_FailingPublisherStore(RuntimeError("second")),  # type: ignore[arg-type]
        schema_catalog=_publisher_catalog(),
    )

    with pytest.raises(RuntimeError):
        first.publish(_publish_request())

    assert first.diagnostic_fallback is not second.diagnostic_fallback
    assert len(first.diagnostic_fallback) == 1
    assert len(second.diagnostic_fallback) == 0
