from __future__ import annotations

import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Event
from typing import Any
from uuid import uuid4

import pytest


pytestmark = pytest.mark.skipif(
    os.getenv("NEWSROOM_RUN_POSTGRES_EVENT_INTEGRATION") != "1",
    reason=(
        "real PostgreSQL durable-event integration is an explicit gate; set "
        "NEWSROOM_RUN_POSTGRES_EVENT_INTEGRATION=1"
    ),
)


@pytest.fixture(scope="module")
def postgres_dsn() -> str:
    dsn = os.getenv("NEWS_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.fail("NEWS_TEST_POSTGRES_DSN is required for the real PostgreSQL gate")

    import psycopg
    from psycopg.conninfo import conninfo_to_dict

    database_name = str(conninfo_to_dict(dsn).get("dbname") or "").casefold()
    if "test" not in database_name:
        pytest.fail("NEWS_TEST_POSTGRES_DSN must select a database containing 'test'")

    migration = (
        Path(__file__).resolve().parents[4]
        / "infrastructure"
        / "storage"
        / "postgres"
        / "migrations"
        / "006_durable_event_runtime.sql"
    ).read_text(encoding="utf-8")
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(migration)
        connection.commit()
    return dsn


@pytest.fixture
def scope(postgres_dsn: str) -> str:
    value = f"pg-durable-{uuid4().hex}"
    yield value
    _cleanup(postgres_dsn, value)


def test_real_postgres_allocates_contiguous_sequences_for_32_writers(
    postgres_dsn: str,
    scope: str,
) -> None:
    from framework.events.runtime import StreamReadRequest
    from infrastructure.storage.events.postgres import PostgresDurableEventStore

    store = PostgresDurableEventStore(postgres_dsn)
    stream_id = f"{scope}:stream"
    tenant_id = f"{scope}:tenant"
    event_count = 32

    def append(index: int) -> int:
        result = store.append_event(
            _candidate(
                scope,
                index=index,
                stream_id=stream_id,
                tenant_id=tenant_id,
            )
        )
        assert result.created
        return result.event.stream_sequence

    with ThreadPoolExecutor(max_workers=12) as executor:
        returned_sequences = list(executor.map(append, range(event_count)))

    assert sorted(returned_sequences) == list(range(1, event_count + 1))
    assert store.get_stream_high_watermark(stream_id, tenant_id=tenant_id) == event_count
    page = store.read_stream(
        StreamReadRequest(
            stream_id=stream_id,
            tenant_id=tenant_id,
            limit=event_count,
        )
    )
    assert [event.stream_sequence for event in page.events] == list(
        range(1, event_count + 1)
    )
    assert {event.event_id for event in page.events} == {
        f"{scope}:event:{index}" for index in range(event_count)
    }
    paged_sequences: list[int] = []
    request = StreamReadRequest(
        stream_id=stream_id,
        tenant_id=tenant_id,
        limit=7,
    )
    while True:
        page = store.read_stream(request)
        paged_sequences.extend(event.stream_sequence for event in page.events)
        if page.next_cursor is None:
            break
        request = StreamReadRequest(
            stream_id=stream_id,
            tenant_id=tenant_id,
            cursor=page.next_cursor,
            limit=7,
        )
    assert paged_sequences == list(range(1, event_count + 1))


def test_factory_composes_real_canonical_postgres_store(
    postgres_dsn: str,
    scope: str,
) -> None:
    from infrastructure.storage.events.factory import event_store_from_env
    from infrastructure.storage.events.postgres import PostgresDurableEventStore

    store = event_store_from_env(env={"NEWS_DATABASE_DSN": postgres_dsn})

    assert isinstance(store, PostgresDurableEventStore)
    result = store.append_event(
        _candidate(scope, index=1, stream_id=f"{scope}:stream")
    )
    assert result.created
    assert result.event.stream_sequence == 1


def test_duplicate_returns_original_record_and_collision_does_not_allocate(
    postgres_dsn: str,
    scope: str,
) -> None:
    from framework.events.errors import EventIdentityCollisionError
    from infrastructure.storage.events.postgres import PostgresDurableEventStore

    store = PostgresDurableEventStore(postgres_dsn)
    stream_id = f"{scope}:stream"
    candidate = _candidate(scope, index=1, stream_id=stream_id)

    first = store.append_event(candidate)
    duplicate = store.append_event(candidate)

    assert first.created
    assert not duplicate.created
    assert duplicate.pending_delivery_count == 0
    assert duplicate.event.to_dict() == first.event.to_dict()
    assert duplicate.event.observed_at == first.event.observed_at
    assert duplicate.event.stream_sequence == 1

    with pytest.raises(EventIdentityCollisionError):
        store.append_event(
            _candidate(
                scope,
                index=1,
                stream_id=stream_id,
                payload={"changed": True},
            )
        )

    second = store.append_event(_candidate(scope, index=2, stream_id=stream_id))
    assert second.event.stream_sequence == 2


def test_32_concurrent_same_id_retries_return_one_committed_sequence(
    postgres_dsn: str,
    scope: str,
) -> None:
    import psycopg

    from infrastructure.storage.events.postgres import PostgresDurableEventStore

    store = PostgresDurableEventStore(postgres_dsn)
    stream_id = f"{scope}:stream"
    candidate = _candidate(scope, index=1, stream_id=stream_id)

    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(lambda _index: store.append_event(candidate), range(32)))

    assert sum(result.created for result in results) == 1
    assert {result.event.stream_sequence for result in results} == {1}
    assert len({result.event.observed_at for result in results}) == 1
    assert len({result.event.record_checksum for result in results}) == 1
    assert store.get_stream_high_watermark(stream_id) == 1

    with psycopg.connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM durable_events WHERE event_id = %s",
                (candidate.event_id,),
            )
            assert int(cursor.fetchone()[0]) == 1

def test_explicit_and_implicit_rollback_leave_no_sequence_gap(
    postgres_dsn: str,
    scope: str,
) -> None:
    from infrastructure.storage.events.postgres import PostgresDurableEventStore

    store = PostgresDurableEventStore(postgres_dsn)
    stream_id = f"{scope}:stream"
    committed = store.append_event(_candidate(scope, index=1, stream_id=stream_id))
    assert committed.event.stream_sequence == 1

    with store.unit_of_work() as unit_of_work:
        rolled_back = unit_of_work.append_event(
            _candidate(scope, index=2, stream_id=stream_id)
        )
        assert rolled_back.event.stream_sequence == 2
        unit_of_work.rollback()

    assert store.get_event(f"{scope}:event:2") is None
    assert store.get_stream_high_watermark(stream_id) == 1

    with store.unit_of_work() as unit_of_work:
        implicitly_rolled_back = unit_of_work.append_event(
            _candidate(scope, index=3, stream_id=stream_id)
        )
        assert implicitly_rolled_back.event.stream_sequence == 2

    assert store.get_event(f"{scope}:event:3") is None
    next_committed = store.append_event(
        _candidate(scope, index=4, stream_id=stream_id)
    )
    assert next_committed.event.stream_sequence == 2


def test_event_and_matching_delivery_commit_atomically_and_duplicate_adds_none(
    postgres_dsn: str,
    scope: str,
) -> None:
    import psycopg

    from framework.events.runtime import DurableSubscription, SubscriptionFilter
    from infrastructure.storage.events.postgres import PostgresDurableEventStore

    store = PostgresDurableEventStore(postgres_dsn)
    event_type = "io.newsroom.test.postgres-durable"
    subscription = DurableSubscription(
        subscription_id=f"{scope}:subscription",
        subscription_version=1,
        consumer_id=f"{scope}:consumer",
        event_filter=SubscriptionFilter(event_types=frozenset({event_type})),
    )
    registered = store.register_subscription(subscription)
    assert registered.subscription_id == subscription.subscription_id

    candidate = _candidate(
        scope,
        index=1,
        stream_id=f"{scope}:stream",
        event_type=event_type,
    )
    first = store.append_event(candidate)
    duplicate = store.append_event(candidate)
    assert first.pending_delivery_count == 1
    assert duplicate.pending_delivery_count == 0

    with psycopg.connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*), min(state), max(stream_sequence)
                FROM event_deliveries
                WHERE subscription_id = %s AND event_id = %s
                """,
                (subscription.subscription_id, candidate.event_id),
            )
            count, state, sequence = cursor.fetchone()
    assert (int(count), str(state), int(sequence)) == (1, "pending", 1)

    with store.unit_of_work() as unit_of_work:
        staged = unit_of_work.append_event(
            _candidate(
                scope,
                index=2,
                stream_id=f"{scope}:stream",
                event_type=event_type,
            )
        )
        assert staged.pending_delivery_count == 1
        unit_of_work.rollback()

    with psycopg.connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM durable_events WHERE event_id = %s",
                (f"{scope}:event:2",),
            )
            event_count = int(cursor.fetchone()[0])
            cursor.execute(
                "SELECT count(*) FROM event_deliveries WHERE event_id = %s",
                (f"{scope}:event:2",),
            )
            delivery_count = int(cursor.fetchone()[0])
    assert (event_count, delivery_count) == (0, 0)


def test_committed_duplicate_returns_when_matching_backlog_is_already_full(
    postgres_dsn: str,
    scope: str,
) -> None:
    from framework.events.runtime import (
        DeliveryLimits,
        DurableSubscription,
        SubscriptionFilter,
        SubscriptionKey,
    )
    from infrastructure.storage.events.postgres import PostgresDurableEventStore

    tenant_id = f"{scope}:tenant"
    stream_id = f"{scope}:duplicate-full-stream"
    event_type = "io.newsroom.test.duplicate-full-backlog"
    subscription = DurableSubscription(
        subscription_id=f"{scope}:duplicate-full-subscription",
        subscription_version=1,
        consumer_id=f"{scope}:duplicate-full-consumer",
        event_filter=SubscriptionFilter(event_types=frozenset({event_type})),
        limits=DeliveryLimits(
            batch_size=1,
            max_in_flight=1,
            max_concurrency=1,
            pending_warning_threshold=1,
            pending_hard_limit=2,
        ),
        tenant_id=tenant_id,
    )
    store = PostgresDurableEventStore(postgres_dsn)
    store.register_subscription(subscription)
    original = _candidate(
        scope,
        index=301,
        stream_id=stream_id,
        tenant_id=tenant_id,
        event_type=event_type,
    )
    first = store.append_event(original)
    store.append_event(
        _candidate(
            scope,
            index=302,
            stream_id=stream_id,
            tenant_id=tenant_id,
            event_type=event_type,
        )
    )

    duplicate = store.append_event(original)

    assert not duplicate.created
    assert duplicate.pending_delivery_count == 0
    assert duplicate.event.event_id == first.event.event_id
    assert duplicate.event.stream_sequence == first.event.stream_sequence == 1
    stats = store.pending_delivery_stats(
        SubscriptionKey(subscription.subscription_id, 1)
    )
    assert stats.pending_count == subscription.limits.pending_hard_limit
    assert store.get_stream_high_watermark(stream_id, tenant_id=tenant_id) == 2


def test_subscription_registration_and_publish_race_has_exactly_one_delivery(
    postgres_dsn: str,
    scope: str,
) -> None:
    import threading

    import psycopg

    from framework.events.runtime import DurableSubscription, SubscriptionFilter
    from infrastructure.storage.events.postgres import PostgresDurableEventStore

    store = PostgresDurableEventStore(postgres_dsn)
    for index in range(12):
        barrier = threading.Barrier(2)
        event_type = f"io.newsroom.test.registration-race.{index}"
        subscription = DurableSubscription(
            subscription_id=f"{scope}:subscription:{index}",
            subscription_version=1,
            consumer_id=f"{scope}:consumer:{index}",
            event_filter=SubscriptionFilter(event_types=frozenset({event_type})),
        )
        candidate = _candidate(
            scope,
            index=index,
            stream_id=f"{scope}:race-stream:{index}",
            event_type=event_type,
        )

        def register() -> None:
            barrier.wait()
            store.register_subscription(subscription)

        def publish() -> None:
            barrier.wait()
            store.append_event(candidate)

        with ThreadPoolExecutor(max_workers=2) as executor:
            register_future = executor.submit(register)
            publish_future = executor.submit(publish)
            register_future.result(timeout=15)
            publish_future.result(timeout=15)

        with psycopg.connect(postgres_dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT count(*)
                    FROM event_deliveries
                    WHERE event_id = %s
                      AND subscription_id = %s
                      AND subscription_version = 1
                    """,
                    (candidate.event_id, subscription.subscription_id),
                )
                assert int(cursor.fetchone()[0]) == 1


def test_concurrent_append_admission_never_exceeds_pending_hard_limit(
    postgres_dsn: str,
    scope: str,
) -> None:
    from framework.events.errors import EventStoreCapacityError
    from framework.events.runtime import (
        DeliveryLimits,
        DeliveryQuery,
        DurableSubscription,
        SubscriptionFilter,
        SubscriptionKey,
    )
    from infrastructure.storage.events.postgres import PostgresDurableEventStore

    tenant_id = f"{scope}:tenant"
    initial_stream_id = f"{scope}:capacity-stream:initial"
    event_type = "io.newsroom.test.pending-capacity-race"
    subscription = DurableSubscription(
        subscription_id=f"{scope}:capacity-subscription",
        subscription_version=1,
        consumer_id=f"{scope}:capacity-consumer",
        event_filter=SubscriptionFilter(event_types=frozenset({event_type})),
        limits=DeliveryLimits(
            batch_size=1,
            max_in_flight=1,
            max_concurrency=1,
            pending_warning_threshold=1,
            pending_hard_limit=2,
        ),
        tenant_id=tenant_id,
    )
    store = PostgresDurableEventStore(postgres_dsn)
    store.register_subscription(subscription)
    store.append_event(
        _candidate(
            scope,
            index=0,
            stream_id=initial_stream_id,
            tenant_id=tenant_id,
            event_type=event_type,
        )
    )

    barrier = Barrier(2)
    concurrent_store = _store_intercepting_capacity_lock(
        postgres_dsn,
        lambda: barrier.wait(timeout=15),
    )
    candidates = tuple(
        _candidate(
            scope,
            index=index,
            stream_id=f"{scope}:capacity-stream:{index}",
            tenant_id=tenant_id,
            event_type=event_type,
        )
        for index in (1, 2)
    )

    def append(candidate: Any) -> tuple[str, str]:
        try:
            return "accepted", concurrent_store.append_event(candidate).event.event_id
        except EventStoreCapacityError:
            return "capacity", candidate.event_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(append, candidates))

    assert sorted(status for status, _event_id in outcomes) == ["accepted", "capacity"]
    accepted_event_id = next(
        event_id for status, event_id in outcomes if status == "accepted"
    )
    rejected_event_id = next(
        event_id for status, event_id in outcomes if status == "capacity"
    )
    deliveries = store.list_deliveries(
        DeliveryQuery(
            subscription_id=subscription.subscription_id,
            subscription_version=1,
            tenant_id=tenant_id,
            limit=10,
        )
    ).records
    stats = store.pending_delivery_stats(
        SubscriptionKey(subscription.subscription_id, 1)
    )

    assert len(deliveries) == subscription.limits.pending_hard_limit
    assert stats.pending_count == subscription.limits.pending_hard_limit
    assert store.get_event(accepted_event_id, tenant_id=tenant_id) is not None
    assert store.get_event(rejected_event_id, tenant_id=tenant_id) is None
    accepted_event = store.get_event(accepted_event_id, tenant_id=tenant_id)
    assert accepted_event is not None
    assert store.get_stream_high_watermark(
        initial_stream_id,
        tenant_id=tenant_id,
    ) == 1
    assert store.get_stream_high_watermark(
        accepted_event.stream_id,
        tenant_id=tenant_id,
    ) == 1
    rejected_stream_id = next(
        candidate.stream_id
        for candidate in candidates
        if candidate.event_id == rejected_event_id
    )
    assert store.get_stream_high_watermark(
        rejected_stream_id,
        tenant_id=tenant_id,
    ) is None


def test_one_full_matching_subscription_rolls_back_other_delivery_and_event(
    postgres_dsn: str,
    scope: str,
) -> None:
    from framework.events.errors import EventStoreCapacityError
    from framework.events.runtime import (
        DeliveryLimits,
        DeliveryQuery,
        DurableSubscription,
        SubscriptionFilter,
    )
    from infrastructure.storage.events.postgres import PostgresDurableEventStore

    tenant_id = f"{scope}:tenant"
    common_type = "io.newsroom.test.multi-subscription-capacity"
    seed_type = "io.newsroom.test.multi-subscription-capacity-seed"
    common_limits = DeliveryLimits(
        batch_size=1,
        max_in_flight=1,
        max_concurrency=1,
        pending_warning_threshold=1,
        pending_hard_limit=2,
    )
    full_limits = DeliveryLimits(
        batch_size=1,
        max_in_flight=1,
        max_concurrency=1,
        pending_warning_threshold=1,
        pending_hard_limit=2,
    )
    subscription_a = DurableSubscription(
        subscription_id=f"{scope}:multi-capacity:a",
        subscription_version=1,
        consumer_id=f"{scope}:multi-capacity-consumer:a",
        event_filter=SubscriptionFilter(event_types=frozenset({common_type})),
        limits=common_limits,
        tenant_id=tenant_id,
    )
    subscription_b = DurableSubscription(
        subscription_id=f"{scope}:multi-capacity:b",
        subscription_version=1,
        consumer_id=f"{scope}:multi-capacity-consumer:b",
        event_filter=SubscriptionFilter(
            event_types=frozenset({common_type, seed_type})
        ),
        limits=full_limits,
        tenant_id=tenant_id,
    )
    store = PostgresDurableEventStore(postgres_dsn)
    store.register_subscription(subscription_a)
    store.register_subscription(subscription_b)
    for index in (400, 401):
        store.append_event(
            _candidate(
                scope,
                index=index,
                stream_id=f"{scope}:multi-capacity-seed-stream",
                tenant_id=tenant_id,
                event_type=seed_type,
            )
        )
    candidate = _candidate(
        scope,
        index=402,
        stream_id=f"{scope}:multi-capacity-final-stream",
        tenant_id=tenant_id,
        event_type=common_type,
    )

    with pytest.raises(EventStoreCapacityError):
        store.append_event(candidate)

    records_a = store.list_deliveries(
        DeliveryQuery(
            subscription_id=subscription_a.subscription_id,
            subscription_version=1,
            tenant_id=tenant_id,
            limit=10,
        )
    ).records
    records_b = store.list_deliveries(
        DeliveryQuery(
            subscription_id=subscription_b.subscription_id,
            subscription_version=1,
            tenant_id=tenant_id,
            limit=10,
        )
    ).records
    assert records_a == ()
    assert len(records_b) == subscription_b.limits.pending_hard_limit
    assert store.get_event(candidate.event_id, tenant_id=tenant_id) is None
    assert store.get_stream_high_watermark(
        candidate.stream_id,
        tenant_id=tenant_id,
    ) is None


def test_registration_backfill_enforces_one_hard_limit_across_all_streams(
    postgres_dsn: str,
    scope: str,
) -> None:
    from framework.events.errors import EventStoreCapacityError
    from framework.events.runtime import (
        DeliveryLimits,
        DeliveryQuery,
        DurableSubscription,
        SubscriptionFilter,
        SubscriptionKey,
    )
    from infrastructure.storage.events.postgres import PostgresDurableEventStore

    tenant_id = f"{scope}:tenant"
    event_type = "io.newsroom.test.registration-capacity"
    store = PostgresDurableEventStore(postgres_dsn)
    for index in range(4):
        store.append_event(
            _candidate(
                scope,
                index=index,
                stream_id=f"{scope}:registration-stream:{index % 2}",
                tenant_id=tenant_id,
                event_type=event_type,
            )
        )

    subscription = DurableSubscription(
        subscription_id=f"{scope}:registration-capacity-subscription",
        subscription_version=1,
        consumer_id=f"{scope}:registration-capacity-consumer",
        event_filter=SubscriptionFilter(event_types=frozenset({event_type})),
        limits=DeliveryLimits(
            batch_size=1,
            max_in_flight=1,
            max_concurrency=1,
            pending_warning_threshold=1,
            pending_hard_limit=3,
        ),
        tenant_id=tenant_id,
    )

    with pytest.raises(EventStoreCapacityError, match="backfill"):
        store.register_subscription(subscription)

    assert store.get_subscription(SubscriptionKey(subscription.subscription_id, 1)) is None
    assert store.list_deliveries(
        DeliveryQuery(
            subscription_id=subscription.subscription_id,
            subscription_version=1,
            tenant_id=tenant_id,
            limit=10,
        )
    ).records == ()


def test_requeue_rejects_when_subscription_pending_capacity_is_full(
    postgres_dsn: str,
    scope: str,
) -> None:
    from framework.events.errors import EventStoreCapacityError
    from framework.events.runtime import (
        DeadLetterAction,
        DeadLetterDisposition,
        DeliveryClaimRequest,
        DeliveryLimits,
        DeliveryQuery,
        DeliverySettlement,
        DeliveryState,
        DurableSubscription,
        SubscriptionFilter,
        SubscriptionKey,
    )
    from infrastructure.storage.events.postgres import PostgresDurableEventStore

    tenant_id = f"{scope}:tenant"
    event_type = "io.newsroom.test.requeue-capacity"
    subscription = DurableSubscription(
        subscription_id=f"{scope}:requeue-capacity-subscription",
        subscription_version=1,
        consumer_id=f"{scope}:requeue-capacity-consumer",
        event_filter=SubscriptionFilter(event_types=frozenset({event_type})),
        limits=DeliveryLimits(
            batch_size=1,
            max_in_flight=1,
            max_concurrency=1,
            pending_warning_threshold=1,
            pending_hard_limit=2,
        ),
        supports_out_of_order_repair=True,
        tenant_id=tenant_id,
    )
    store = PostgresDurableEventStore(postgres_dsn)
    store.register_subscription(subscription)
    store.append_event(
        _candidate(
            scope,
            index=0,
            stream_id=f"{scope}:requeue-dead-stream",
            tenant_id=tenant_id,
            event_type=event_type,
        )
    )
    now = datetime.now(UTC)
    claim = store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=subscription.subscription_id,
            subscription_version=1,
            lease_owner="worker-dead",
            requested_at=now,
            limit=1,
        )
    )[0]
    dead = store.settle_delivery(
        DeliverySettlement(
            lease=claim.lease,
            target_state=DeliveryState.DEAD_LETTER,
            settled_at=now + timedelta(seconds=1),
            reason_class="permanent",
            redacted_diagnostic="bounded permanent failure",
        )
    )
    assert dead.dead_letter_id is not None
    for index in (1, 2):
        store.append_event(
            _candidate(
                scope,
                index=index,
                stream_id=f"{scope}:requeue-capacity-stream:{index}",
                tenant_id=tenant_id,
                event_type=event_type,
            )
        )

    with pytest.raises(EventStoreCapacityError, match="hard limit"):
        store.requeue_dead_letter(
            DeadLetterAction(
                dead_letter_id=dead.dead_letter_id,
                operator_id="operator-capacity",
                reason="capacity must be reserved",
                requested_at=now + timedelta(seconds=2),
                idempotency_ready=True,
            )
        )

    dead_letter = store.get_dead_letter(dead.dead_letter_id, tenant_id=tenant_id)
    assert dead_letter is not None
    assert dead_letter.disposition is DeadLetterDisposition.OPEN
    deliveries = store.list_deliveries(
        DeliveryQuery(
            subscription_id=subscription.subscription_id,
            subscription_version=1,
            tenant_id=tenant_id,
            limit=10,
        )
    ).records
    assert len(deliveries) == 3
    assert max(record.delivery_generation for record in deliveries) == 1
    assert store.pending_delivery_stats(
        SubscriptionKey(subscription.subscription_id, 1)
    ).pending_count == 2


def test_requeue_and_append_share_one_pending_capacity_fence(
    postgres_dsn: str,
    scope: str,
) -> None:
    from framework.events.errors import EventStoreCapacityError
    from framework.events.runtime import (
        DeadLetterAction,
        DeadLetterDisposition,
        DeliveryClaimRequest,
        DeliveryLimits,
        DeliverySettlement,
        DeliveryState,
        DurableSubscription,
        SubscriptionFilter,
        SubscriptionKey,
    )
    from infrastructure.storage.events.postgres import PostgresDurableEventStore

    tenant_id = f"{scope}:tenant"
    event_type = "io.newsroom.test.requeue-append-capacity-race"
    subscription = DurableSubscription(
        subscription_id=f"{scope}:requeue-race-subscription",
        subscription_version=1,
        consumer_id=f"{scope}:requeue-race-consumer",
        event_filter=SubscriptionFilter(event_types=frozenset({event_type})),
        limits=DeliveryLimits(
            batch_size=1,
            max_in_flight=1,
            max_concurrency=1,
            pending_warning_threshold=1,
            pending_hard_limit=2,
        ),
        supports_out_of_order_repair=True,
        tenant_id=tenant_id,
    )
    store = PostgresDurableEventStore(postgres_dsn)
    store.register_subscription(subscription)
    store.append_event(
        _candidate(
            scope,
            index=0,
            stream_id=f"{scope}:requeue-race-dead",
            tenant_id=tenant_id,
            event_type=event_type,
        )
    )
    now = datetime.now(UTC)
    claim = store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=subscription.subscription_id,
            subscription_version=1,
            lease_owner="worker-dead",
            requested_at=now,
            limit=1,
        )
    )[0]
    dead = store.settle_delivery(
        DeliverySettlement(
            lease=claim.lease,
            target_state=DeliveryState.DEAD_LETTER,
            settled_at=now + timedelta(seconds=1),
            reason_class="permanent",
            redacted_diagnostic="bounded permanent failure",
        )
    )
    assert dead.dead_letter_id is not None
    store.append_event(
        _candidate(
            scope,
            index=1,
            stream_id=f"{scope}:requeue-race-existing",
            tenant_id=tenant_id,
            event_type=event_type,
        )
    )
    candidate = _candidate(
        scope,
        index=2,
        stream_id=f"{scope}:requeue-race-append",
        tenant_id=tenant_id,
        event_type=event_type,
    )
    action = DeadLetterAction(
        dead_letter_id=dead.dead_letter_id,
        operator_id="operator-race",
        reason="race for final pending slot",
        requested_at=now + timedelta(seconds=2),
        idempotency_ready=True,
    )
    barrier = Barrier(2)
    concurrent_store = _store_intercepting_capacity_lock(
        postgres_dsn,
        lambda: barrier.wait(timeout=15),
    )

    def requeue() -> str:
        try:
            concurrent_store.requeue_dead_letter(action)
            return "requeue-accepted"
        except EventStoreCapacityError:
            return "requeue-capacity"

    def append() -> str:
        try:
            concurrent_store.append_event(candidate)
            return "append-accepted"
        except EventStoreCapacityError:
            return "append-capacity"

    with ThreadPoolExecutor(max_workers=2) as executor:
        requeue_future = executor.submit(requeue)
        append_future = executor.submit(append)
        outcomes = {requeue_future.result(timeout=15), append_future.result(timeout=15)}

    assert outcomes in (
        {"requeue-accepted", "append-capacity"},
        {"requeue-capacity", "append-accepted"},
    )
    assert store.pending_delivery_stats(
        SubscriptionKey(subscription.subscription_id, 1)
    ).pending_count == 2
    dead_letter = store.get_dead_letter(dead.dead_letter_id, tenant_id=tenant_id)
    assert dead_letter is not None
    if "requeue-accepted" in outcomes:
        assert dead_letter.disposition is DeadLetterDisposition.REQUEUED
        assert store.get_event(candidate.event_id, tenant_id=tenant_id) is None
    else:
        assert dead_letter.disposition is DeadLetterDisposition.OPEN
        assert store.get_event(candidate.event_id, tenant_id=tenant_id) is not None


def test_uow_capacity_tracker_allows_same_key_and_ascending_mixed_mutations(
    postgres_dsn: str,
    scope: str,
) -> None:
    from framework.events.runtime import (
        DeliveryClaimRequest,
        DeliveryLimits,
        DeliveryQuery,
        DeliverySettlement,
        DeliveryState,
        DurableSubscription,
        SubscriptionFilter,
    )
    from infrastructure.storage.events.postgres import PostgresDurableEventStore

    tenant_id = f"{scope}:tenant"
    event_type_a = "io.newsroom.test.capacity-order-a"
    event_type_b = "io.newsroom.test.capacity-order-b"
    limits = DeliveryLimits(
        batch_size=1,
        max_in_flight=1,
        max_concurrency=1,
        pending_warning_threshold=2,
        pending_hard_limit=6,
    )
    subscription_a = DurableSubscription(
        subscription_id=f"{scope}:capacity-order:a",
        subscription_version=1,
        consumer_id=f"{scope}:capacity-order-consumer:a",
        event_filter=SubscriptionFilter(event_types=frozenset({event_type_a})),
        limits=limits,
        tenant_id=tenant_id,
    )
    subscription_b = DurableSubscription(
        subscription_id=f"{scope}:capacity-order:b",
        subscription_version=1,
        consumer_id=f"{scope}:capacity-order-consumer:b",
        event_filter=SubscriptionFilter(event_types=frozenset({event_type_b})),
        limits=limits,
        tenant_id=tenant_id,
    )
    store = PostgresDurableEventStore(postgres_dsn)
    store.register_subscription(subscription_a)
    store.register_subscription(subscription_b)
    store.append_event(
        _candidate(
            scope,
            index=0,
            stream_id=f"{scope}:capacity-order-seed",
            tenant_id=tenant_id,
            event_type=event_type_a,
        )
    )
    now = datetime.now(UTC)
    claim = store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=subscription_a.subscription_id,
            subscription_version=1,
            lease_owner="worker-order",
            requested_at=now,
            limit=1,
        )
    )[0]
    same_key = _candidate(
        scope,
        index=1,
        stream_id=f"{scope}:capacity-order-same",
        tenant_id=tenant_id,
        event_type=event_type_a,
    )
    ascending_key = _candidate(
        scope,
        index=2,
        stream_id=f"{scope}:capacity-order-ascending",
        tenant_id=tenant_id,
        event_type=event_type_b,
    )

    with store.unit_of_work() as transaction:
        transaction.settle_delivery(
            DeliverySettlement(
                lease=claim.lease,
                target_state=DeliveryState.ACKED,
                settled_at=now + timedelta(seconds=1),
            )
        )
        transaction.append_event(same_key)
        transaction.append_event(ascending_key)
        transaction.commit()

    assert store.get_event(same_key.event_id, tenant_id=tenant_id) is not None
    assert store.get_event(ascending_key.event_id, tenant_id=tenant_id) is not None
    records_a = store.list_deliveries(
        DeliveryQuery(
            subscription_id=subscription_a.subscription_id,
            subscription_version=1,
            tenant_id=tenant_id,
            limit=10,
        )
    ).records
    records_b = store.list_deliveries(
        DeliveryQuery(
            subscription_id=subscription_b.subscription_id,
            subscription_version=1,
            tenant_id=tenant_id,
            limit=10,
        )
    ).records
    assert sorted(record.state.value for record in records_a) == ["acked", "pending"]
    assert [record.state for record in records_b] == [DeliveryState.PENDING]


def test_uow_capacity_tracker_rejects_reverse_key_order_and_rolls_back(
    postgres_dsn: str,
    scope: str,
) -> None:
    from framework.events.errors import EventStoreContentionError, EventStoreError
    from framework.events.runtime import (
        DeliveryClaimRequest,
        DeliveryLimits,
        DeliveryQuery,
        DeliverySettlement,
        DeliveryState,
        DurableSubscription,
        SubscriptionFilter,
    )
    from infrastructure.storage.events.postgres import PostgresDurableEventStore

    tenant_id = f"{scope}:tenant"
    event_type_a = "io.newsroom.test.capacity-reverse-a"
    event_type_b = "io.newsroom.test.capacity-reverse-b"
    limits = DeliveryLimits(
        batch_size=1,
        max_in_flight=1,
        max_concurrency=1,
        pending_warning_threshold=2,
        pending_hard_limit=6,
    )
    subscription_a = DurableSubscription(
        subscription_id=f"{scope}:capacity-reverse:a",
        subscription_version=1,
        consumer_id=f"{scope}:capacity-reverse-consumer:a",
        event_filter=SubscriptionFilter(event_types=frozenset({event_type_a})),
        limits=limits,
        tenant_id=tenant_id,
    )
    subscription_b = DurableSubscription(
        subscription_id=f"{scope}:capacity-reverse:b",
        subscription_version=1,
        consumer_id=f"{scope}:capacity-reverse-consumer:b",
        event_filter=SubscriptionFilter(event_types=frozenset({event_type_b})),
        limits=limits,
        tenant_id=tenant_id,
    )
    store = PostgresDurableEventStore(postgres_dsn)
    store.register_subscription(subscription_a)
    store.register_subscription(subscription_b)
    store.append_event(
        _candidate(
            scope,
            index=0,
            stream_id=f"{scope}:capacity-reverse-seed",
            tenant_id=tenant_id,
            event_type=event_type_b,
        )
    )
    now = datetime.now(UTC)
    claim = store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=subscription_b.subscription_id,
            subscription_version=1,
            lease_owner="worker-reverse",
            requested_at=now,
            limit=1,
        )
    )[0]
    reverse_candidate = _candidate(
        scope,
        index=1,
        stream_id=f"{scope}:capacity-reverse-lower",
        tenant_id=tenant_id,
        event_type=event_type_a,
    )

    with store.unit_of_work() as transaction:
        transaction.settle_delivery(
            DeliverySettlement(
                lease=claim.lease,
                target_state=DeliveryState.ACKED,
                settled_at=now + timedelta(seconds=1),
            )
        )
        observed_sql: list[tuple[str, object]] = []

        def observe(query: object, params: object) -> None:
            observed_sql.append((str(query), params))

        original_cursor = transaction.connection.cursor

        def cursor(*args: object, **kwargs: object) -> Any:
            return _SqlInterceptingCursor(
                original_cursor(*args, **kwargs),
                observe,
                None,
            )

        transaction.connection.cursor = cursor
        try:
            with pytest.raises(EventStoreContentionError, match="canonical order"):
                transaction.append_event(reverse_candidate)
        finally:
            transaction.connection.cursor = original_cursor
        with pytest.raises(EventStoreError, match="rollback-only"):
            transaction.commit()

    subscription_reads = [
        sql
        for sql, _params in observed_sql
        if "FROM event_subscriptions" in sql
    ]
    assert len(subscription_reads) == 1
    assert "FOR SHARE" not in subscription_reads[0]
    assert not any(
        isinstance(params, tuple)
        and params
        and isinstance(params[0], str)
        and (
            params[0].startswith("event:")
            or params[0].startswith("event-stream-sequence:")
        )
        for _sql, params in observed_sql
    )

    assert store.get_event(reverse_candidate.event_id, tenant_id=tenant_id) is None
    records = store.list_deliveries(
        DeliveryQuery(
            subscription_id=subscription_b.subscription_id,
            subscription_version=1,
            tenant_id=tenant_id,
            limit=10,
        )
    ).records
    assert len(records) == 1
    assert records[0].state is DeliveryState.CLAIMED
    assert records[0].lease_owner == "worker-reverse"
    assert store.get_stream_high_watermark(
        reverse_candidate.stream_id,
        tenant_id=tenant_id,
    ) is None


def test_opposite_event_uow_orders_fail_fast_and_one_transaction_commits(
    postgres_dsn: str,
    scope: str,
) -> None:
    from framework.events.errors import EventStoreContentionError, EventStoreError
    from framework.events.runtime import (
        DeliveryLimits,
        DurableSubscription,
        SubscriptionFilter,
    )
    from infrastructure.storage.events.postgres import PostgresDurableEventStore

    tenant_id = f"{scope}:tenant"
    event_type_a = "io.newsroom.test.event-lock-order-a"
    event_type_b = "io.newsroom.test.event-lock-order-b"
    limits = DeliveryLimits(
        batch_size=1,
        max_in_flight=1,
        max_concurrency=1,
        pending_warning_threshold=3,
        pending_hard_limit=8,
    )
    subscription_a = DurableSubscription(
        subscription_id=f"{scope}:event-lock-order:a",
        subscription_version=1,
        consumer_id=f"{scope}:event-lock-order-consumer:a",
        event_filter=SubscriptionFilter(event_types=frozenset({event_type_a})),
        limits=limits,
        tenant_id=tenant_id,
    )
    subscription_b = DurableSubscription(
        subscription_id=f"{scope}:event-lock-order:b",
        subscription_version=1,
        consumer_id=f"{scope}:event-lock-order-consumer:b",
        event_filter=SubscriptionFilter(event_types=frozenset({event_type_b})),
        limits=limits,
        tenant_id=tenant_id,
    )
    store = PostgresDurableEventStore(postgres_dsn)
    store.register_subscription(subscription_a)
    store.register_subscription(subscription_b)
    event_a = _candidate(
        scope,
        index=101,
        stream_id=f"{scope}:event-lock-order-stream-a",
        tenant_id=tenant_id,
        event_type=event_type_a,
    )
    event_b = _candidate(
        scope,
        index=102,
        stream_id=f"{scope}:event-lock-order-stream-b",
        tenant_id=tenant_id,
        event_type=event_type_b,
    )
    forward_has_a = Event()
    reverse_has_b = Event()
    forward_failed_on_b = Event()
    both_failed = Barrier(2)

    def forward_order() -> str:
        with store.unit_of_work() as transaction:
            transaction.connection.execute("SET LOCAL lock_timeout = '2s'")
            transaction.connection.execute("SET LOCAL statement_timeout = '5s'")
            transaction.append_event(event_a)
            forward_has_a.set()
            assert reverse_has_b.wait(timeout=10)
            try:
                with pytest.raises(
                    EventStoreContentionError,
                    match="lock contention",
                ):
                    transaction.append_event(event_b)
                forward_failed_on_b.set()
                both_failed.wait(timeout=10)
                with pytest.raises(EventStoreError, match="rollback-only"):
                    transaction.commit()
            finally:
                forward_failed_on_b.set()
        return "forward-rolled-back"

    def reverse_order() -> str:
        assert forward_has_a.wait(timeout=10)
        with store.unit_of_work() as transaction:
            transaction.connection.execute("SET LOCAL lock_timeout = '2s'")
            transaction.connection.execute("SET LOCAL statement_timeout = '5s'")
            transaction.append_event(event_b)
            reverse_has_b.set()
            assert forward_failed_on_b.wait(timeout=10)
            with pytest.raises(
                EventStoreContentionError,
                match="canonical order",
            ):
                transaction.append_event(event_a)
            both_failed.wait(timeout=10)
            with pytest.raises(EventStoreError, match="rollback-only"):
                transaction.commit()
        return "reverse-rolled-back"

    with ThreadPoolExecutor(max_workers=2) as executor:
        forward = executor.submit(forward_order)
        reverse = executor.submit(reverse_order)
        assert {reverse.result(timeout=15), forward.result(timeout=15)} == {
            "reverse-rolled-back",
            "forward-rolled-back",
        }

    assert store.get_event(event_a.event_id, tenant_id=tenant_id) is None
    assert store.get_event(event_b.event_id, tenant_id=tenant_id) is None

    with store.unit_of_work() as retry:
        retry.connection.execute("SET LOCAL lock_timeout = '2s'")
        retry.connection.execute("SET LOCAL statement_timeout = '5s'")
        retry.append_event(event_a)
        retry.append_event(event_b)
        retry.commit()

    committed_a = store.get_event(event_a.event_id, tenant_id=tenant_id)
    committed_b = store.get_event(event_b.event_id, tenant_id=tenant_id)
    assert committed_a is not None
    assert committed_b is not None
    assert committed_a.stream_sequence == 1
    assert committed_b.stream_sequence == 1


def test_crossed_settle_and_append_uows_fail_fast_then_release_for_commit(
    postgres_dsn: str,
    scope: str,
) -> None:
    from framework.events.errors import EventStoreContentionError, EventStoreError
    from framework.events.runtime import (
        DeliveryClaimRequest,
        DeliveryLimits,
        DeliveryQuery,
        DeliverySettlement,
        DeliveryState,
        DurableSubscription,
        SubscriptionFilter,
    )
    from infrastructure.storage.events.postgres import PostgresDurableEventStore

    tenant_id = f"{scope}:tenant"
    event_type_a = "io.newsroom.test.crossed-uow-a"
    event_type_b = "io.newsroom.test.crossed-uow-b"
    limits = DeliveryLimits(
        batch_size=1,
        max_in_flight=1,
        max_concurrency=1,
        pending_warning_threshold=2,
        pending_hard_limit=6,
    )
    subscription_a = DurableSubscription(
        subscription_id=f"{scope}:crossed-uow:a",
        subscription_version=1,
        consumer_id=f"{scope}:crossed-uow-consumer:a",
        event_filter=SubscriptionFilter(event_types=frozenset({event_type_a})),
        limits=limits,
        tenant_id=tenant_id,
    )
    subscription_b = DurableSubscription(
        subscription_id=f"{scope}:crossed-uow:b",
        subscription_version=1,
        consumer_id=f"{scope}:crossed-uow-consumer:b",
        event_filter=SubscriptionFilter(event_types=frozenset({event_type_b})),
        limits=limits,
        tenant_id=tenant_id,
    )
    store = PostgresDurableEventStore(postgres_dsn)
    store.register_subscription(subscription_a)
    store.register_subscription(subscription_b)
    store.append_event(
        _candidate(
            scope,
            index=200,
            stream_id=f"{scope}:crossed-uow-seed-b",
            tenant_id=tenant_id,
            event_type=event_type_b,
        )
    )
    now = datetime.now(UTC)
    claim_b = store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=subscription_b.subscription_id,
            subscription_version=1,
            lease_owner="worker-crossed-uow",
            requested_at=now,
            limit=1,
        )
    )[0]
    event_a = _candidate(
        scope,
        index=201,
        stream_id=f"{scope}:crossed-uow-stream-a",
        tenant_id=tenant_id,
        event_type=event_type_a,
    )
    reverse_settled_b = Event()
    forward_appended_a = Event()
    reverse_released_b = Event()

    def reverse_order() -> str:
        with store.unit_of_work() as transaction:
            transaction.connection.execute("SET LOCAL lock_timeout = '2s'")
            transaction.connection.execute("SET LOCAL statement_timeout = '5s'")
            try:
                transaction.settle_delivery(
                    DeliverySettlement(
                        lease=claim_b.lease,
                        target_state=DeliveryState.ACKED,
                        settled_at=now + timedelta(seconds=1),
                    )
                )
                reverse_settled_b.set()
                assert forward_appended_a.wait(timeout=10)
                with pytest.raises(
                    EventStoreContentionError,
                    match="canonical order",
                ):
                    transaction.append_event(event_a)
                with pytest.raises(EventStoreError, match="rollback-only"):
                    transaction.commit()
            finally:
                reverse_released_b.set()
        return "reverse-rolled-back"

    def forward_order() -> str:
        assert reverse_settled_b.wait(timeout=10)
        with store.unit_of_work() as transaction:
            transaction.connection.execute("SET LOCAL lock_timeout = '2s'")
            transaction.connection.execute("SET LOCAL statement_timeout = '5s'")
            transaction.append_event(event_a)
            forward_appended_a.set()
            assert reverse_released_b.wait(timeout=10)
            transaction.settle_delivery(
                DeliverySettlement(
                    lease=claim_b.lease,
                    target_state=DeliveryState.ACKED,
                    settled_at=now + timedelta(seconds=2),
                )
            )
            transaction.commit()
        return "forward-committed"

    with ThreadPoolExecutor(max_workers=2) as executor:
        reverse = executor.submit(reverse_order)
        forward = executor.submit(forward_order)
        assert {reverse.result(timeout=15), forward.result(timeout=15)} == {
            "reverse-rolled-back",
            "forward-committed",
        }

    assert store.get_event(event_a.event_id, tenant_id=tenant_id) is not None
    deliveries = store.list_deliveries(
        DeliveryQuery(
            subscription_id=subscription_b.subscription_id,
            subscription_version=1,
            tenant_id=tenant_id,
            limit=10,
        )
    ).records
    assert len(deliveries) == 1
    assert deliveries[0].state is DeliveryState.ACKED


def test_capacity_lock_keys_isolate_tenant_and_subscription_version(
    postgres_dsn: str,
    scope: str,
) -> None:
    import psycopg

    from framework.events.runtime import DeliveryLimits, DurableSubscription
    from infrastructure.storage.events.postgres import (
        _lock_subscription_delivery_capacity,
        _subscription_delivery_capacity_lock_key,
        _subscription_delivery_capacity_lock_name,
    )

    limits = DeliveryLimits(
        batch_size=1,
        max_in_flight=1,
        max_concurrency=1,
        pending_warning_threshold=2,
        pending_hard_limit=6,
    )
    subscription_id = f"{scope}:capacity-key-isolation"
    tenant_a = f"{scope}:tenant-a"
    subscriptions = (
        DurableSubscription(
            subscription_id=subscription_id,
            subscription_version=1,
            consumer_id=f"{scope}:consumer:tenant-a:v1",
            limits=limits,
            tenant_id=tenant_a,
        ),
        DurableSubscription(
            subscription_id=subscription_id,
            subscription_version=2,
            consumer_id=f"{scope}:consumer:tenant-a:v2",
            limits=limits,
            tenant_id=tenant_a,
        ),
        DurableSubscription(
            subscription_id=subscription_id,
            subscription_version=1,
            consumer_id=f"{scope}:consumer:tenant-b:v1",
            limits=limits,
            tenant_id=f"{scope}:tenant-b",
        ),
    )
    lock_keys = {
        _subscription_delivery_capacity_lock_key(item) for item in subscriptions
    }
    lock_names = {
        _subscription_delivery_capacity_lock_name(item) for item in subscriptions
    }
    assert len(lock_keys) == 3
    assert len(lock_names) == 3

    holder_ready = Event()
    release_holder = Event()

    def hold_first_key() -> str:
        with psycopg.connect(postgres_dsn) as connection:
            with connection.cursor() as cursor:
                _lock_subscription_delivery_capacity(cursor, subscriptions[0])
                holder_ready.set()
                assert release_holder.wait(timeout=10)
            connection.rollback()
        return "holder-released"

    def acquire_isolated_keys() -> str:
        assert holder_ready.wait(timeout=10)
        try:
            with psycopg.connect(postgres_dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = '1s'")
                    cursor.execute("SET LOCAL statement_timeout = '3s'")
                    _lock_subscription_delivery_capacity(cursor, subscriptions[1])
                    _lock_subscription_delivery_capacity(cursor, subscriptions[2])
                connection.rollback()
        finally:
            release_holder.set()
        return "isolated-keys-acquired"

    with ThreadPoolExecutor(max_workers=2) as executor:
        holder = executor.submit(hold_first_key)
        isolated = executor.submit(acquire_isolated_keys)
        assert {holder.result(timeout=15), isolated.result(timeout=15)} == {
            "holder-released",
            "isolated-keys-acquired",
        }


def test_rolled_back_pending_reservation_releases_capacity_without_sequence_leak(
    postgres_dsn: str,
    scope: str,
) -> None:
    from framework.events.runtime import (
        DeliveryLimits,
        DurableSubscription,
        SubscriptionFilter,
        SubscriptionKey,
    )
    from infrastructure.storage.events.postgres import PostgresDurableEventStore

    tenant_id = f"{scope}:tenant"
    stream_id = f"{scope}:rollback-capacity-stream"
    event_type = "io.newsroom.test.pending-capacity-rollback"
    subscription = DurableSubscription(
        subscription_id=f"{scope}:rollback-capacity-subscription",
        subscription_version=1,
        consumer_id=f"{scope}:rollback-capacity-consumer",
        event_filter=SubscriptionFilter(event_types=frozenset({event_type})),
        limits=DeliveryLimits(
            batch_size=1,
            max_in_flight=1,
            max_concurrency=1,
            pending_warning_threshold=1,
            pending_hard_limit=2,
        ),
        tenant_id=tenant_id,
    )
    store = PostgresDurableEventStore(postgres_dsn)
    store.register_subscription(subscription)
    store.append_event(
        _candidate(
            scope,
            index=0,
            stream_id=stream_id,
            tenant_id=tenant_id,
            event_type=event_type,
        )
    )
    rolled_back = _candidate(
        scope,
        index=1,
        stream_id=stream_id,
        tenant_id=tenant_id,
        event_type=event_type,
    )
    committed = _candidate(
        scope,
        index=2,
        stream_id=stream_id,
        tenant_id=tenant_id,
        event_type=event_type,
    )
    waiter_reached_fence = Event()
    waiting_store = _store_intercepting_capacity_lock(
        postgres_dsn,
        waiter_reached_fence.set,
    )

    with store.unit_of_work() as transaction:
        staged = transaction.append_event(rolled_back)
        assert staged.pending_delivery_count == 1
        with ThreadPoolExecutor(max_workers=1) as executor:
            waiting_append = executor.submit(waiting_store.append_event, committed)
            assert waiter_reached_fence.wait(timeout=15)
            assert not waiting_append.done()
            transaction.rollback()
            accepted = waiting_append.result(timeout=15)

    stats = store.pending_delivery_stats(
        SubscriptionKey(subscription.subscription_id, 1)
    )
    assert accepted.created
    assert stats.pending_count == subscription.limits.pending_hard_limit
    assert store.get_event(rolled_back.event_id, tenant_id=tenant_id) is None
    assert store.get_event(committed.event_id, tenant_id=tenant_id) is not None
    assert store.get_stream_high_watermark(stream_id, tenant_id=tenant_id) == 2


def test_concurrent_claims_never_exceed_max_in_flight(
    postgres_dsn: str,
    scope: str,
) -> None:
    from framework.events.runtime import (
        DeliveryClaimRequest,
        DeliveryLimits,
        DeliveryQuery,
        DeliveryState,
        DurableSubscription,
        SubscriptionFilter,
    )
    from infrastructure.storage.events.postgres import PostgresDurableEventStore

    tenant_id = f"{scope}:tenant"
    event_type = "io.newsroom.test.in-flight-capacity-race"
    subscription = DurableSubscription(
        subscription_id=f"{scope}:in-flight-subscription",
        subscription_version=1,
        consumer_id=f"{scope}:in-flight-consumer",
        event_filter=SubscriptionFilter(event_types=frozenset({event_type})),
        limits=DeliveryLimits(
            batch_size=2,
            max_in_flight=2,
            max_concurrency=1,
            pending_warning_threshold=4,
            pending_hard_limit=10,
        ),
        tenant_id=tenant_id,
    )
    store = PostgresDurableEventStore(postgres_dsn)
    store.register_subscription(subscription)
    for index in range(4):
        store.append_event(
            _candidate(
                scope,
                index=index,
                stream_id=f"{scope}:in-flight-stream:{index}",
                tenant_id=tenant_id,
                event_type=event_type,
            )
        )

    barrier = Barrier(2)
    concurrent_store = _store_intercepting_capacity_lock(
        postgres_dsn,
        lambda: barrier.wait(timeout=15),
    )
    requested_at = datetime.now(UTC)
    requests = tuple(
        DeliveryClaimRequest(
            subscription_id=subscription.subscription_id,
            subscription_version=1,
            lease_owner=f"worker-{index}",
            requested_at=requested_at,
            limit=2,
        )
        for index in range(2)
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = tuple(executor.map(concurrent_store.claim_deliveries, requests))

    records = store.list_deliveries(
        DeliveryQuery(
            subscription_id=subscription.subscription_id,
            subscription_version=1,
            tenant_id=tenant_id,
            limit=10,
        )
    ).records
    claimed_count = sum(record.state is DeliveryState.CLAIMED for record in records)
    assert sorted(len(batch) for batch in claims) == [0, 2]
    assert claimed_count == subscription.limits.max_in_flight
    assert sum(len(batch) for batch in claims) == subscription.limits.max_in_flight


def test_claims_enforce_durable_lease_owner_concurrency_slots(
    postgres_dsn: str,
    scope: str,
) -> None:
    from framework.events.runtime import (
        DeliveryClaimRequest,
        DeliveryLimits,
        DeliverySettlement,
        DeliveryState,
        DurableSubscription,
        SubscriptionFilter,
    )
    from infrastructure.storage.events.postgres import PostgresDurableEventStore

    tenant_id = f"{scope}:tenant"
    event_type = "io.newsroom.test.lease-owner-concurrency"
    subscription = DurableSubscription(
        subscription_id=f"{scope}:owner-slot-subscription",
        subscription_version=1,
        consumer_id=f"{scope}:owner-slot-consumer",
        event_filter=SubscriptionFilter(event_types=frozenset({event_type})),
        limits=DeliveryLimits(
            batch_size=2,
            max_in_flight=3,
            max_concurrency=2,
            pending_warning_threshold=5,
            pending_hard_limit=10,
        ),
        tenant_id=tenant_id,
    )
    store = PostgresDurableEventStore(postgres_dsn)
    store.register_subscription(subscription)
    for index in range(5):
        store.append_event(
            _candidate(
                scope,
                index=index,
                stream_id=f"{scope}:owner-slot-stream:{index}",
                tenant_id=tenant_id,
                event_type=event_type,
            )
        )

    requested_at = datetime.now(UTC)

    def claim(lease_owner: str) -> tuple[Any, ...]:
        return store.claim_deliveries(
            DeliveryClaimRequest(
                subscription_id=subscription.subscription_id,
                subscription_version=1,
                lease_owner=lease_owner,
                requested_at=requested_at,
                limit=1,
            )
        )

    first_a = claim("worker-a")
    first_b = claim("worker-b")
    assert len(first_a) == 1
    assert len(first_b) == 1
    assert claim("worker-c") == ()

    second_a = claim("worker-a")
    assert len(second_a) == 1
    assert claim("worker-a") == ()

    store.settle_delivery(
        DeliverySettlement(
            lease=first_b[0].lease,
            target_state=DeliveryState.ACKED,
            settled_at=datetime.now(UTC),
        )
    )
    first_c = claim("worker-c")
    assert len(first_c) == 1
    assert {
        first_a[0].lease.lease_owner,
        second_a[0].lease.lease_owner,
        first_c[0].lease.lease_owner,
    } == {"worker-a", "worker-c"}


def test_rolled_back_claim_releases_in_flight_capacity_and_lease(
    postgres_dsn: str,
    scope: str,
) -> None:
    from framework.events.runtime import (
        DeliveryClaimRequest,
        DeliveryLimits,
        DeliveryQuery,
        DeliveryState,
        DurableSubscription,
        SubscriptionFilter,
    )
    from infrastructure.storage.events.postgres import PostgresDurableEventStore

    tenant_id = f"{scope}:tenant"
    event_type = "io.newsroom.test.in-flight-capacity-rollback"
    subscription = DurableSubscription(
        subscription_id=f"{scope}:claim-rollback-subscription",
        subscription_version=1,
        consumer_id=f"{scope}:claim-rollback-consumer",
        event_filter=SubscriptionFilter(event_types=frozenset({event_type})),
        limits=DeliveryLimits(
            batch_size=1,
            max_in_flight=1,
            max_concurrency=1,
            pending_warning_threshold=2,
            pending_hard_limit=4,
        ),
        tenant_id=tenant_id,
    )
    store = PostgresDurableEventStore(postgres_dsn)
    store.register_subscription(subscription)
    store.append_event(
        _candidate(
            scope,
            index=0,
            stream_id=f"{scope}:claim-rollback-stream",
            tenant_id=tenant_id,
            event_type=event_type,
        )
    )
    failure_injected = False

    def fail_after_claim_update(query: object, _params: object) -> None:
        nonlocal failure_injected
        normalized = " ".join(str(query).split())
        if (
            not failure_injected
            and "UPDATE event_deliveries" in normalized
            and "SET state = 'claimed'" in normalized
        ):
            failure_injected = True
            raise RuntimeError("injected failure after claimed-row update")

    failing_store = _store_intercepting_sql(
        postgres_dsn,
        after_execute=fail_after_claim_update,
    )
    requested_at = datetime.now(UTC)
    with pytest.raises(RuntimeError, match="injected failure"):
        failing_store.claim_deliveries(
            DeliveryClaimRequest(
                subscription_id=subscription.subscription_id,
                subscription_version=1,
                lease_owner="worker-failed",
                requested_at=requested_at,
                limit=1,
            )
        )

    records_after_rollback = store.list_deliveries(
        DeliveryQuery(
            subscription_id=subscription.subscription_id,
            subscription_version=1,
            tenant_id=tenant_id,
            limit=10,
        )
    ).records
    assert failure_injected
    assert len(records_after_rollback) == 1
    assert records_after_rollback[0].state is DeliveryState.PENDING
    assert records_after_rollback[0].attempt_count == 0
    assert records_after_rollback[0].lease_owner is None

    recovered = store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=subscription.subscription_id,
            subscription_version=1,
            lease_owner="worker-recovered",
            requested_at=requested_at + timedelta(seconds=1),
            limit=1,
        )
    )
    assert len(recovered) == 1
    assert recovered[0].delivery.attempt_count == 1
    assert recovered[0].lease.lease_owner == "worker-recovered"


def test_subscription_status_change_is_monotonic_and_audited_atomically(
    postgres_dsn: str,
    scope: str,
) -> None:
    import psycopg

    from framework.events.runtime import DurableSubscription, SubscriptionStatus
    from infrastructure.storage.events.postgres import PostgresDurableEventStore

    store = PostgresDurableEventStore(postgres_dsn)
    registered = store.register_subscription(
        DurableSubscription(
            subscription_id=f"{scope}:status-audit",
            subscription_version=1,
            consumer_id=f"{scope}:status-consumer",
            tenant_id=f"{scope}:tenant",
        )
    )
    assert registered.updated_at is not None
    changed_at = registered.updated_at + timedelta(seconds=1)

    paused = store.set_subscription_status(
        registered.key,
        SubscriptionStatus.PAUSED,
        changed_at=changed_at,
        reason="  maintenance window  ",
    )

    assert paused.status is SubscriptionStatus.PAUSED
    assert paused.updated_at == changed_at
    with psycopg.connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT previous_status, new_status, changed_at, reason
                FROM event_subscription_status_audit
                WHERE subscription_id = %s AND subscription_version = 1
                ORDER BY audit_id
                """,
                (registered.subscription_id,),
            )
            assert cursor.fetchall() == [
                ("active", "paused", changed_at, "maintenance window")
            ]

    with pytest.raises(ValueError, match="cannot precede"):
        store.set_subscription_status(
            registered.key,
            SubscriptionStatus.ACTIVE,
            changed_at=changed_at - timedelta(microseconds=1),
            reason="stale operator command",
        )

    persisted = store.get_subscription(registered.key)
    assert persisted is not None
    assert persisted.status is SubscriptionStatus.PAUSED
    assert persisted.updated_at == changed_at
    with psycopg.connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*)
                FROM event_subscription_status_audit
                WHERE subscription_id = %s AND subscription_version = 1
                """,
                (registered.subscription_id,),
            )
            assert int(cursor.fetchone()[0]) == 1

    retired_at = changed_at + timedelta(seconds=1)
    retired = store.set_subscription_status(
        registered.key,
        SubscriptionStatus.RETIRED,
        changed_at=retired_at,
        reason="replace retired consumer",
    )
    assert retired.status is SubscriptionStatus.RETIRED
    with psycopg.connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT previous_status, new_status, changed_at, reason
                FROM event_subscription_status_audit
                WHERE subscription_id = %s AND subscription_version = 1
                ORDER BY audit_id
                """,
                (registered.subscription_id,),
            )
            assert cursor.fetchall() == [
                ("active", "paused", changed_at, "maintenance window"),
                (
                    "paused",
                    "retired",
                    retired_at,
                    "replace retired consumer",
                ),
            ]


def test_reregistration_ignores_subscription_lifecycle_fields(
    postgres_dsn: str,
    scope: str,
) -> None:
    from dataclasses import replace

    from framework.events.runtime import DurableSubscription, SubscriptionStatus
    from infrastructure.storage.events.postgres import PostgresDurableEventStore

    store = PostgresDurableEventStore(postgres_dsn)
    original_time = datetime(2026, 7, 1, 8, 0, tzinfo=UTC)
    definition = DurableSubscription(
        subscription_id=f"{scope}:lifecycle-definition",
        subscription_version=1,
        consumer_id=f"{scope}:lifecycle-consumer",
        tenant_id=f"{scope}:tenant",
        created_at=original_time,
        updated_at=original_time,
    )
    registered = store.register_subscription(definition)
    paused = store.set_subscription_status(
        registered.key,
        SubscriptionStatus.PAUSED,
        changed_at=original_time + timedelta(minutes=1),
        reason="pause before duplicate registration",
    )

    duplicate_active = replace(
        definition,
        status=SubscriptionStatus.ACTIVE,
        created_at=original_time + timedelta(days=1),
        updated_at=original_time + timedelta(days=2),
    )
    assert store.register_subscription(duplicate_active) == paused

    retired = store.set_subscription_status(
        registered.key,
        SubscriptionStatus.RETIRED,
        changed_at=original_time + timedelta(minutes=2),
        reason="retire before duplicate registration",
    )
    assert store.register_subscription(duplicate_active) == retired


def test_reader_fails_closed_on_record_checksum_corruption(
    postgres_dsn: str,
    scope: str,
) -> None:
    import psycopg

    from framework.events.errors import EventStoreCorruptionError
    from infrastructure.storage.events.postgres import PostgresDurableEventStore

    store = PostgresDurableEventStore(postgres_dsn)
    candidate = _candidate(scope, index=1, stream_id=f"{scope}:stream")
    stored = store.append_event(candidate).event

    with psycopg.connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE durable_events SET record_checksum = %s WHERE event_id = %s",
                ("sha256:" + "0" * 64, candidate.event_id),
            )
        connection.commit()

    with pytest.raises(EventStoreCorruptionError):
        store.get_event(candidate.event_id)

    with psycopg.connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE durable_events SET record_checksum = %s WHERE event_id = %s",
                (stored.record_checksum, candidate.event_id),
            )
        connection.commit()


def test_delivery_lease_retry_inbox_checkpoint_and_late_repair(
    postgres_dsn: str,
    scope: str,
) -> None:
    import psycopg

    from framework.events.errors import EventStaleLeaseError
    from framework.events.runtime import (
        CheckpointKey,
        ConsumerEffectContract,
        DeadLetterAction,
        DeliveryClaimRequest,
        DeliveryQuery,
        DeliverySettlement,
        DeliveryState,
        DurableSubscription,
        EffectIdempotencyStrategy,
        InboxEntry,
        InboxKey,
        SubscriptionFilter,
        SubscriptionKey,
    )
    from infrastructure.storage.events.postgres import PostgresDurableEventStore

    store = PostgresDurableEventStore(postgres_dsn)
    event_type = "io.newsroom.test.delivery"
    subscription = DurableSubscription(
        subscription_id=f"{scope}:subscription",
        subscription_version=1,
        consumer_id=f"{scope}:consumer",
        event_filter=SubscriptionFilter(event_types=frozenset({event_type})),
        effect=ConsumerEffectContract(
            performs_external_effects=True,
            consumer_effect_id=f"{scope}:effect",
            idempotency_strategy=EffectIdempotencyStrategy.INBOX_TRANSACTION,
        ),
        supports_out_of_order_repair=True,
    )
    store.register_subscription(subscription)
    stream_id = f"{scope}:stream"
    first_event = store.append_event(
        _candidate(scope, index=1, stream_id=stream_id, event_type=event_type)
    ).event
    second_event = store.append_event(
        _candidate(scope, index=2, stream_id=stream_id, event_type=event_type)
    ).event
    now = datetime.now(UTC)

    first_delivery_page = store.list_deliveries(
        DeliveryQuery(subscription_id=subscription.subscription_id, limit=1)
    )
    assert [item.stream_sequence for item in first_delivery_page.records] == [1]
    assert first_delivery_page.next_cursor is not None
    second_delivery_page = store.list_deliveries(
        DeliveryQuery(
            subscription_id=subscription.subscription_id,
            cursor=first_delivery_page.next_cursor,
            limit=1,
        )
    )
    assert [item.stream_sequence for item in second_delivery_page.records] == [2]

    first_claims = store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=subscription.subscription_id,
            subscription_version=1,
            lease_owner="worker-a",
            requested_at=now,
            limit=10,
        )
    )
    assert [claim.delivery.stream_sequence for claim in first_claims] == [1]
    first_claim = first_claims[0]
    retry_at = now + timedelta(seconds=10)
    retry_result = store.settle_delivery(
        DeliverySettlement(
            lease=first_claim.lease,
            target_state=DeliveryState.RETRY_WAIT,
            settled_at=now + timedelta(seconds=1),
            reason_class="transient",
            redacted_diagnostic="bounded transient failure",
            retry_available_at=retry_at,
        )
    )
    assert retry_result.delivery.state is DeliveryState.RETRY_WAIT
    assert retry_result.checkpoint is None
    assert store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=subscription.subscription_id,
            subscription_version=1,
            lease_owner="worker-b",
            requested_at=now + timedelta(seconds=5),
            limit=10,
        )
    ) == ()

    with psycopg.connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE event_deliveries
                SET available_at = clock_timestamp() - interval '1 second'
                WHERE delivery_id = %s
                """,
                (retry_result.delivery.delivery_id,),
            )
        connection.commit()

    retry_claim = store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=subscription.subscription_id,
            subscription_version=1,
            lease_owner="worker-b",
            requested_at=now - timedelta(days=1),
            limit=10,
        )
    )[0]
    assert retry_claim.delivery.stream_sequence == 1
    assert retry_claim.delivery.attempt_count == 2
    assert retry_claim.lease.lease_generation == 2
    with pytest.raises(EventStaleLeaseError):
        store.settle_delivery(
            DeliverySettlement(
                lease=first_claim.lease,
                target_state=DeliveryState.ACKED,
                settled_at=now + timedelta(seconds=2),
            )
        )

    first_inbox = InboxEntry(
        event_id=first_event.event_id,
        consumer_effect_id=subscription.effect.consumer_effect_id,
        completed_at=now + timedelta(seconds=11),
        delivery_id=retry_claim.delivery.delivery_id,
        result_checksum="sha256:" + "1" * 64,
    )
    ack = store.settle_delivery(
        DeliverySettlement(
            lease=retry_claim.lease,
            target_state=DeliveryState.ACKED,
            settled_at=now + timedelta(seconds=11),
            inbox_entry=first_inbox,
        )
    )
    assert ack.inbox_recorded
    assert ack.checkpoint.highest_contiguous_terminal_sequence == 1
    assert store.get_inbox_entry(
        InboxKey(first_event.event_id, subscription.effect.consumer_effect_id)
    ) == first_inbox

    second_claim = store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=subscription.subscription_id,
            subscription_version=1,
            lease_owner="worker-c",
            requested_at=now + timedelta(seconds=12),
            limit=10,
        )
    )[0]
    assert second_claim.delivery.stream_sequence == 2
    dead = store.settle_delivery(
        DeliverySettlement(
            lease=second_claim.lease,
            target_state=DeliveryState.DEAD_LETTER,
            settled_at=now + timedelta(seconds=13),
            reason_class="permanent",
            redacted_diagnostic="bounded permanent failure",
        )
    )
    assert dead.dead_letter_id is not None
    assert dead.checkpoint.highest_contiguous_terminal_sequence == 2
    checkpoint = store.get_checkpoint(
        CheckpointKey(
            subscription_id=subscription.subscription_id,
            subscription_version=1,
            stream_id=stream_id,
        )
    )
    assert checkpoint == dead.checkpoint
    assert checkpoint.last_event_id == second_event.event_id
    assert checkpoint.terminal_disposition is DeliveryState.DEAD_LETTER
    assert store.pending_delivery_stats(SubscriptionKey(subscription.subscription_id, 1)).lag == 0

    repair = store.requeue_dead_letter(
        DeadLetterAction(
            dead_letter_id=dead.dead_letter_id,
            operator_id="operator-a",
            reason="authorized repair",
            requested_at=now + timedelta(seconds=14),
            idempotency_ready=True,
        )
    )
    assert repair.delivery_generation == 2
    repair_claim = store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=subscription.subscription_id,
            subscription_version=1,
            lease_owner="worker-repair",
            requested_at=now + timedelta(seconds=15),
            limit=10,
        )
    )[0]
    assert repair_claim.delivery.delivery_generation == 2
    repair_ack = store.settle_delivery(
        DeliverySettlement(
            lease=repair_claim.lease,
            target_state=DeliveryState.ACKED,
            settled_at=now + timedelta(seconds=16),
            inbox_entry=InboxEntry(
                event_id=second_event.event_id,
                consumer_effect_id=subscription.effect.consumer_effect_id,
                completed_at=now + timedelta(seconds=16),
                delivery_id=repair_claim.delivery.delivery_id,
                result_checksum="sha256:" + "2" * 64,
            ),
        )
    )
    assert repair_ack.delivery.state is DeliveryState.ACKED
    assert repair_ack.checkpoint is None
    assert store.get_checkpoint(
        CheckpointKey(subscription.subscription_id, 1, stream_id)
    ) == checkpoint


def test_pending_delivery_stats_separate_frontier_lag_and_late_repair(
    postgres_dsn: str,
    scope: str,
) -> None:
    from framework.events.errors import EventStoreError
    from framework.events.runtime import (
        DeadLetterAction,
        DeliveryClaimRequest,
        DeliveryLimits,
        DeliverySettlement,
        DeliveryState,
        DurableSubscription,
        SubscriptionFilter,
        SubscriptionKey,
    )
    from infrastructure.storage.events.postgres import PostgresDurableEventStore

    tenant_id = f"{scope}:tenant"
    stream_id = f"{scope}:pending-stats-stream"
    event_type = "io.newsroom.test.pending-stats"
    subscription = DurableSubscription(
        subscription_id=f"{scope}:pending-stats-subscription",
        subscription_version=1,
        consumer_id=f"{scope}:pending-stats-consumer",
        event_filter=SubscriptionFilter(event_types=frozenset({event_type})),
        limits=DeliveryLimits(
            batch_size=1,
            max_in_flight=1,
            max_concurrency=1,
            pending_warning_threshold=2,
            pending_hard_limit=4,
        ),
        supports_out_of_order_repair=True,
        tenant_id=tenant_id,
    )
    store = PostgresDurableEventStore(postgres_dsn)
    store.register_subscription(subscription)
    for index in range(2):
        store.append_event(
            _candidate(
                scope,
                index=index,
                stream_id=stream_id,
                tenant_id=tenant_id,
                event_type=event_type,
            )
        )

    now = datetime.now(UTC)
    first_claim = store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=subscription.subscription_id,
            subscription_version=1,
            lease_owner="pending-stats-worker",
            requested_at=now,
            limit=1,
        )
    )[0]
    dead_letter = store.settle_delivery(
        DeliverySettlement(
            lease=first_claim.lease,
            target_state=DeliveryState.DEAD_LETTER,
            settled_at=now,
            reason_class="permanent",
            redacted_diagnostic="bounded permanent failure",
        )
    )
    store.requeue_dead_letter(
        DeadLetterAction(
            dead_letter_id=dead_letter.dead_letter_id,
            operator_id="pending-stats-operator",
            reason="exercise late repair diagnostics",
            requested_at=datetime.now(UTC),
            idempotency_ready=True,
        )
    )

    stats = store.pending_delivery_stats(subscription.key)
    assert stats.pending_count == 2
    assert stats.lag == 1
    assert stats.late_repair_pending_count == 1
    assert stats.warning_threshold_reached
    assert stats.capacity_remaining == 2
    assert stats.oldest_pending_at is not None
    assert stats.oldest_pending_age_seconds is not None
    assert stats.oldest_pending_age_seconds >= 0
    stream_stats = store.pending_delivery_stats(
        subscription.key,
        stream_id=stream_id,
    )
    assert (
        stream_stats.pending_count,
        stream_stats.lag,
        stream_stats.late_repair_pending_count,
        stream_stats.warning_threshold_reached,
        stream_stats.capacity_remaining,
        stream_stats.oldest_pending_at,
    ) == (
        stats.pending_count,
        stats.lag,
        stats.late_repair_pending_count,
        stats.warning_threshold_reached,
        stats.capacity_remaining,
        stats.oldest_pending_at,
    )
    assert stream_stats.oldest_pending_age_seconds is not None
    assert stream_stats.oldest_pending_age_seconds >= 0

    with pytest.raises(EventStoreError, match="subscription does not exist"):
        store.pending_delivery_stats(
            SubscriptionKey(f"{scope}:unknown-subscription", 1)
        )


def test_expired_lease_recovery_and_renewal_fence_stale_tokens(
    postgres_dsn: str,
    scope: str,
) -> None:
    from dataclasses import replace

    import psycopg

    from framework.events.errors import EventStaleLeaseError
    from framework.events.runtime import (
        DeliveryClaimRequest,
        DeliverySettlement,
        DeliveryState,
        DurableSubscription,
        SubscriptionFilter,
    )
    from infrastructure.storage.events.postgres import PostgresDurableEventStore

    store = PostgresDurableEventStore(postgres_dsn)
    event_type = "io.newsroom.test.lease-recovery"
    subscription = DurableSubscription(
        subscription_id=f"{scope}:subscription",
        subscription_version=1,
        consumer_id=f"{scope}:consumer",
        event_filter=SubscriptionFilter(event_types=frozenset({event_type})),
    )
    store.register_subscription(subscription)
    store.append_event(
        _candidate(
            scope,
            index=1,
            stream_id=f"{scope}:stream",
            event_type=event_type,
        )
    )

    def database_now() -> datetime:
        with psycopg.connect(postgres_dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT clock_timestamp()")
                row = cursor.fetchone()
        assert row is not None
        return row[0]

    backdated = datetime(2020, 1, 1, tzinfo=UTC)
    database_before_claim = database_now()
    first = store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=subscription.subscription_id,
            subscription_version=1,
            lease_owner="worker-old",
            requested_at=backdated,
            lease_duration_seconds=30,
        )
    )[0]
    database_after_claim = database_now()
    assert first.lease.lease_expires_at >= database_before_claim + timedelta(
        seconds=30
    )
    assert first.lease.lease_expires_at <= database_after_claim + timedelta(
        seconds=30
    )
    assert first.lease.lease_expires_at > backdated + timedelta(days=1)

    with psycopg.connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE event_deliveries
                SET lease_expires_at = clock_timestamp() - interval '1 second',
                    updated_at = GREATEST(updated_at, clock_timestamp())
                WHERE delivery_id = %s
                RETURNING lease_expires_at, updated_at
                """,
                (first.delivery.delivery_id,),
            )
            expired_row = cursor.fetchone()
        connection.commit()
    assert expired_row is not None
    expired_at = expired_row[0]
    expired_updated_at = expired_row[1]
    expired_token = replace(
        first.lease,
        lease_expires_at=expired_at,
        lease_started_at=None,
    )

    with pytest.raises(EventStaleLeaseError):
        store.renew_delivery_lease(
            expired_token,
            renewed_at=backdated,
            lease_duration_seconds=30,
        )
    with pytest.raises(EventStaleLeaseError):
        store.settle_delivery(
            DeliverySettlement(
                lease=expired_token,
                target_state=DeliveryState.ACKED,
                settled_at=backdated,
            )
        )

    recovered = store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=subscription.subscription_id,
            subscription_version=1,
            lease_owner="worker-new",
            requested_at=backdated - timedelta(days=1),
            lease_duration_seconds=30,
        )
    )[0]
    assert recovered.delivery.attempt_count == 2
    assert recovered.lease.lease_generation == 2
    assert recovered.delivery.first_failure_at is not None
    assert recovered.delivery.last_failure_at is not None
    assert recovered.delivery.updated_at is not None
    assert recovered.delivery.first_failure_at >= expired_updated_at
    assert recovered.delivery.last_failure_at >= expired_updated_at
    assert recovered.delivery.updated_at >= expired_updated_at

    database_before_renew = database_now()
    renewed = store.renew_delivery_lease(
        recovered.lease,
        renewed_at=recovered.lease.lease_expires_at + timedelta(days=1),
        lease_duration_seconds=30,
    )
    database_after_renew = database_now()
    assert renewed.lease_expires_at >= database_before_renew + timedelta(seconds=30)
    assert renewed.lease_expires_at <= database_after_renew + timedelta(seconds=30)

    with pytest.raises(EventStaleLeaseError):
        store.settle_delivery(
            DeliverySettlement(
                lease=first.lease,
                target_state=DeliveryState.ACKED,
                settled_at=backdated,
            )
        )
    with pytest.raises(EventStaleLeaseError):
        store.settle_delivery(
            DeliverySettlement(
                lease=recovered.lease,
                target_state=DeliveryState.ACKED,
                settled_at=backdated,
            )
        )
    settled = store.settle_delivery(
        DeliverySettlement(
            lease=renewed,
            target_state=DeliveryState.ACKED,
            settled_at=renewed.lease_expires_at + timedelta(days=1),
        )
    )
    assert settled.delivery.state is DeliveryState.ACKED
    assert settled.delivery.updated_at >= recovered.delivery.updated_at
    assert settled.delivery.first_failure_at >= expired_updated_at
    assert settled.delivery.last_failure_at >= expired_updated_at


def test_quarantine_and_replay_reports_are_durable_and_tenant_scoped(
    postgres_dsn: str,
    scope: str,
) -> None:
    from dataclasses import replace

    from framework.events.runtime import (
        QuarantineDisposition,
        QuarantineQuery,
        QuarantineReason,
        QuarantineRecord,
        ReplayReportQuery,
        ReplayStartRequest,
        ReplayStatus,
        ReplayVersion,
    )
    from infrastructure.storage.events.postgres import PostgresDurableEventStore

    store = PostgresDurableEventStore(postgres_dsn)
    tenant_id = f"{scope}:tenant"
    stream_id = f"{scope}:stream"
    store.append_event(
        _candidate(scope, index=1, stream_id=stream_id, tenant_id=tenant_id)
    )
    store.append_event(
        _candidate(scope, index=2, stream_id=stream_id, tenant_id=tenant_id)
    )
    now = datetime.now(UTC)

    quarantine = QuarantineRecord(
        quarantine_id=f"{scope}:quarantine:1",
        source="legacy-jsonl:line-7",
        reason=QuarantineReason.CORRUPT_RECORD,
        created_at=now,
        envelope_schema="newsroom.event/v1",
        event_type="legacy_event",
        tenant_id=tenant_id,
        redacted_diagnostic="checksum mismatch",
    )
    assert store.save_quarantine(quarantine) == quarantine
    assert store.save_quarantine(quarantine) == quarantine
    assert store.get_quarantine(quarantine.quarantine_id, tenant_id=tenant_id) == quarantine
    assert store.get_quarantine(quarantine.quarantine_id) is None
    assert store.list_quarantine(
        QuarantineQuery(tenant_id=tenant_id, limit=1)
    ).records == (quarantine,)
    resolved = store.resolve_quarantine(
        quarantine.quarantine_id,
        QuarantineDisposition.REJECTED,
        operator_id="operator-a",
        reason="verified corrupt source",
        resolved_at=now + timedelta(seconds=1),
    )
    assert resolved.disposition is QuarantineDisposition.REJECTED

    request = ReplayStartRequest(
        replay_id=f"{scope}:replay:1",
        mode="verify_history",
        source_stream_id=stream_id,
        requested_at=now + timedelta(seconds=2),
        from_sequence=1,
        tenant_id=tenant_id,
    )
    pending = store.begin_replay(request)
    assert pending.high_watermark == 2
    store.append_event(
        _candidate(scope, index=3, stream_id=stream_id, tenant_id=tenant_id)
    )
    assert store.get_replay_report(pending.replay_id, tenant_id=tenant_id).high_watermark == 2
    running = store.update_replay_report(replace(pending, status=ReplayStatus.RUNNING))
    completed = store.update_replay_report(
        replace(
            running,
            status=ReplayStatus.SUCCEEDED,
            to_sequence=2,
            versions=(ReplayVersion("workflow", "1"),),
            result_checksum="sha256:" + "3" * 64,
            finished_at=now + timedelta(seconds=3),
        )
    )
    assert completed.high_watermark == 2
    assert completed.status is ReplayStatus.SUCCEEDED
    assert store.list_replay_reports(
        ReplayReportQuery(tenant_id=tenant_id, limit=1)
    ).reports == (completed,)
    with pytest.raises(Exception, match="terminal replay report is immutable"):
        store.update_replay_report(replace(completed, to_sequence=1))


def _candidate(
    scope: str,
    *,
    index: int,
    stream_id: str,
    tenant_id: str | None = None,
    event_type: str = "io.newsroom.test.postgres-durable",
    payload: dict[str, object] | None = None,
):
    from framework.events.canonical import (
        BusinessContext,
        EventCandidate,
        ProducerIdentity,
    )

    return EventCandidate(
        event_id=f"{scope}:event:{index}",
        event_type=event_type,
        data_schema="newsroom.test.postgres-durable/v1",
        source="tests.infrastructure.storage.events",
        occurred_at=datetime(2026, 7, 15, 3, 0, tzinfo=UTC),
        stream_id=stream_id,
        business_context=BusinessContext(run_id=scope),
        producer=ProducerIdentity(component="postgres-durable-test", version="1"),
        tenant_id=tenant_id,
        payload=payload if payload is not None else {"index": index},
    )


class _SqlInterceptingCursor:
    def __init__(
        self,
        cursor: Any,
        before_execute: Callable[[object, object], object] | None,
        after_execute: Callable[[object, object], object] | None,
    ) -> None:
        self._cursor = cursor
        self._before_execute = before_execute
        self._after_execute = after_execute

    def __enter__(self) -> _SqlInterceptingCursor:
        self._cursor.__enter__()
        return self

    def __exit__(self, *args: object) -> object:
        return self._cursor.__exit__(*args)

    def execute(
        self,
        query: object,
        params: object = None,
        *args: object,
        **kwargs: object,
    ) -> object:
        if self._before_execute is not None:
            self._before_execute(query, params)
        result = self._cursor.execute(query, params, *args, **kwargs)
        if self._after_execute is not None:
            self._after_execute(query, params)
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cursor, name)


class _SqlInterceptingConnection:
    def __init__(
        self,
        connection: Any,
        before_execute: Callable[[object, object], object] | None,
        after_execute: Callable[[object, object], object] | None,
    ) -> None:
        self._connection = connection
        self._before_execute = before_execute
        self._after_execute = after_execute

    def __enter__(self) -> _SqlInterceptingConnection:
        self._connection.__enter__()
        return self

    def __exit__(self, *args: object) -> object:
        return self._connection.__exit__(*args)

    def cursor(self, *args: object, **kwargs: object) -> Any:
        return _SqlInterceptingCursor(
            self._connection.cursor(*args, **kwargs),
            self._before_execute,
            self._after_execute,
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


def _store_intercepting_capacity_lock(
    dsn: str,
    before_capacity_lock: Callable[[], object],
) -> Any:
    def before_execute(_query: object, params: object) -> None:
        if _is_delivery_capacity_lock(params):
            before_capacity_lock()

    return _store_intercepting_sql(dsn, before_execute=before_execute)


def _store_intercepting_sql(
    dsn: str,
    *,
    before_execute: Callable[[object, object], object] | None = None,
    after_execute: Callable[[object, object], object] | None = None,
) -> Any:
    import psycopg

    from infrastructure.storage.events.postgres import PostgresDurableEventStore

    return PostgresDurableEventStore(
        dsn,
        connection_factory=lambda: _SqlInterceptingConnection(
            psycopg.connect(dsn),
            before_execute,
            after_execute,
        ),
    )


def _is_delivery_capacity_lock(params: object) -> bool:
    return (
        isinstance(params, tuple)
        and bool(params)
        and isinstance(params[0], str)
        and params[0].startswith("event-subscription-delivery-capacity:")
    )


def _cleanup(dsn: str, scope: str) -> None:
    import psycopg

    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM event_inbox WHERE event_id LIKE %s",
                (f"{scope}:%",),
            )
            cursor.execute(
                "DELETE FROM event_dead_letters WHERE event_id LIKE %s",
                (f"{scope}:%",),
            )
            cursor.execute(
                "DELETE FROM event_deliveries WHERE event_id LIKE %s",
                (f"{scope}:%",),
            )
            cursor.execute(
                "DELETE FROM event_consumer_checkpoints WHERE subscription_id LIKE %s",
                (f"{scope}:%",),
            )
            cursor.execute(
                "DELETE FROM event_subscription_stream_states WHERE subscription_id LIKE %s",
                (f"{scope}:%",),
            )
            cursor.execute(
                "DELETE FROM event_subscription_status_audit WHERE subscription_id LIKE %s",
                (f"{scope}:%",),
            )
            cursor.execute(
                "DELETE FROM event_subscriptions WHERE subscription_id LIKE %s",
                (f"{scope}:%",),
            )
            cursor.execute(
                "DELETE FROM event_replay_reports WHERE replay_id LIKE %s",
                (f"{scope}:%",),
            )
            cursor.execute(
                "DELETE FROM event_quarantine WHERE quarantine_id LIKE %s",
                (f"{scope}:%",),
            )
            cursor.execute(
                "DELETE FROM durable_events WHERE event_id LIKE %s",
                (f"{scope}:%",),
            )
            cursor.execute(
                "DELETE FROM event_stream_sequences WHERE stream_id LIKE %s",
                (f"{scope}:%",),
            )
        connection.commit()
