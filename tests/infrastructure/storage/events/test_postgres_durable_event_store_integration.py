from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
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

    retry_claim = store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=subscription.subscription_id,
            subscription_version=1,
            lease_owner="worker-b",
            requested_at=retry_at,
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


def test_expired_lease_recovery_and_renewal_fence_stale_tokens(
    postgres_dsn: str,
    scope: str,
) -> None:
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
    now = datetime.now(UTC)
    first = store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=subscription.subscription_id,
            subscription_version=1,
            lease_owner="worker-old",
            requested_at=now,
            lease_duration_seconds=5,
        )
    )[0]
    recovered = store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=subscription.subscription_id,
            subscription_version=1,
            lease_owner="worker-new",
            requested_at=now + timedelta(seconds=6),
            lease_duration_seconds=5,
        )
    )[0]
    assert recovered.delivery.attempt_count == 2
    assert recovered.lease.lease_generation == 2
    renewed = store.renew_delivery_lease(
        recovered.lease,
        renewed_at=now + timedelta(seconds=7),
        lease_duration_seconds=5,
    )
    with pytest.raises(EventStaleLeaseError):
        store.settle_delivery(
            DeliverySettlement(
                lease=first.lease,
                target_state=DeliveryState.ACKED,
                settled_at=now + timedelta(seconds=1),
            )
        )
    with pytest.raises(EventStaleLeaseError):
        store.settle_delivery(
            DeliverySettlement(
                lease=recovered.lease,
                target_state=DeliveryState.ACKED,
                settled_at=now + timedelta(seconds=8),
            )
        )
    settled = store.settle_delivery(
        DeliverySettlement(
            lease=renewed,
            target_state=DeliveryState.ACKED,
            settled_at=now + timedelta(seconds=8),
        )
    )
    assert settled.delivery.state is DeliveryState.ACKED


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
