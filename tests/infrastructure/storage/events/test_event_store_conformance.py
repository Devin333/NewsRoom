from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from time import monotonic, sleep
from typing import Iterator
from uuid import uuid4

import pytest

from framework.events.canonical import (
    BusinessContext,
    EventCandidate,
    ProducerIdentity,
    StoredEvent,
    canonical_json_bytes,
    checksum_for,
)
from framework.events.errors import (
    EventConsumerIdempotencyError,
    EventIdentityCollisionError,
    EventRetirementCancellationCollisionError,
    EventRetirementCancellationError,
    EventSchemaValidationError,
    EventSecurityError,
    EventStaleLeaseError,
    EventStoreCapacityError,
    EventStoreError,
    EventSubscriptionPositionError,
)
from framework.events.ports import EventStorePort
from framework.events.runtime.models import (
    CheckpointKey,
    ConsumerEffectContract,
    DeadLetterAction,
    DeadLetterDisposition,
    DeadLetterQuery,
    DeliveryClaimRequest,
    DeliveryLimits,
    DeliveryQuery,
    DeliverySettlement,
    DeliveryState,
    DurableSubscription,
    EffectIdempotencyStrategy,
    InboxEntry,
    InboxKey,
    RedeliveryRequest,
    RetirementCancellationRequest,
    ReplayMode,
    ReplayStartRequest,
    ReplayStatus,
    RetryPolicy,
    StreamReadRequest,
    SubscriptionFilter,
    SubscriptionKey,
    SubscriptionStart,
    SubscriptionStartPolicy,
    SubscriptionStatus,
)
from framework.events.runtime.publisher import EventPublishRequest, EventRuntime
from framework.events.schema import (
    EventSchemaCatalog,
    EventSchemaRegistration,
    SecurityClassification,
    SensitivityPolicy,
)
from infrastructure.storage.events.sqlite import SQLiteEventStore


OCCURRED_AT = datetime(2026, 7, 15, 3, 0, tzinfo=UTC)
SQLITE_OBSERVED_AT = datetime(2026, 7, 15, 3, 0, 1, tzinfo=UTC)
NORMALIZED_OBSERVED_AT = datetime(2026, 7, 15, 3, 0, 2, tzinfo=UTC)
RUNTIME_EVENT_TYPE = "io.newsroom.test.runtime-security"
RUNTIME_DATA_SCHEMA = "newsroom.test.runtime-security/v1"
RAW_RUNTIME_SECRET = "runtime-secret-must-never-persist"


@dataclass(frozen=True)
class EventStoreCase:
    backend: str
    store: EventStorePort
    scope: str
    now: Callable[[], datetime]
    advance_clock: Callable[[datetime], None]


@dataclass
class MutableClock:
    current: datetime

    def __call__(self) -> datetime:
        return self.current

    def advance_to(self, value: datetime) -> None:
        if value > self.current:
            self.current = value


@dataclass(frozen=True)
class CrossBackendEventStores:
    scope: str
    sqlite: SQLiteEventStore
    postgres: EventStorePort


def _wait_for_database_clock(dsn: str, value: datetime) -> None:
    import psycopg

    deadline = monotonic() + 15
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            while True:
                cursor.execute("SELECT clock_timestamp()")
                database_now = cursor.fetchone()[0]
                if database_now >= value:
                    return
                if monotonic() >= deadline:
                    raise AssertionError(
                        "PostgreSQL clock did not reach the lease boundary"
                    )
                remaining = (value - database_now).total_seconds()
                sleep(min(0.05, max(0.001, remaining)))


@pytest.fixture(scope="session")
def postgres_conformance_dsn() -> str:
    dsn = os.getenv("NEWS_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip(
            "PostgreSQL event-store conformance requires NEWS_TEST_POSTGRES_DSN"
        )
    assert dsn is not None
    psycopg = pytest.importorskip("psycopg")
    from psycopg.conninfo import conninfo_to_dict

    database_name = str(conninfo_to_dict(dsn).get("dbname") or "").casefold()
    if "test" not in database_name:
        pytest.fail(
            "NEWS_TEST_POSTGRES_DSN must select a database containing 'test'"
        )
    migrations = (
        Path(__file__).resolve().parents[4]
        / "infrastructure"
        / "storage"
        / "postgres"
        / "migrations"
    )
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            for migration_name in (
                "006_durable_event_runtime.sql",
                "008_authorized_redelivery.sql",
                "010_retirement_cancellations.sql",
            ):
                cursor.execute(
                    (migrations / migration_name).read_text(encoding="utf-8")
                )
        connection.commit()
    return dsn


@pytest.fixture(params=("sqlite", "postgres"))
def event_store_case(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> Iterator[EventStoreCase]:
    scope = f"event-store-conformance:{uuid4().hex}"
    if request.param == "sqlite":
        clock = MutableClock(SQLITE_OBSERVED_AT)
        yield EventStoreCase(
            backend="sqlite",
            store=SQLiteEventStore(
                tmp_path / "events.sqlite3",
                clock=clock,
            ),
            scope=scope,
            now=clock,
            advance_clock=clock.advance_to,
        )
        return

    dsn = request.getfixturevalue("postgres_conformance_dsn")
    from infrastructure.storage.events.postgres import PostgresDurableEventStore

    _cleanup_postgres_scope(dsn, scope)
    try:
        yield EventStoreCase(
            backend="postgres",
            store=PostgresDurableEventStore(dsn),
            scope=scope,
            now=lambda: datetime.now(UTC),
            advance_clock=lambda value: _wait_for_database_clock(dsn, value),
        )
    finally:
        _cleanup_postgres_scope(dsn, scope)


@pytest.fixture
def cross_backend_event_stores(
    tmp_path: Path,
    postgres_conformance_dsn: str,
) -> Iterator[CrossBackendEventStores]:
    from infrastructure.storage.events.postgres import PostgresDurableEventStore

    scope = f"event-runtime-conformance:{uuid4().hex}"
    _cleanup_postgres_scope(postgres_conformance_dsn, scope)
    try:
        yield CrossBackendEventStores(
            scope=scope,
            sqlite=SQLiteEventStore(
                tmp_path / "runtime-cross-backend.sqlite3",
                clock=lambda: SQLITE_OBSERVED_AT,
            ),
            postgres=PostgresDurableEventStore(postgres_conformance_dsn),
        )
    finally:
        _cleanup_postgres_scope(postgres_conformance_dsn, scope)


def test_conformance_canonical_bytes_and_checksums_round_trip(
    event_store_case: EventStoreCase,
) -> None:
    case = event_store_case
    candidate = _candidate(case.scope, index=1)
    expected_content_bytes = canonical_json_bytes(candidate.content_projection())
    expected_content_checksum = checksum_for(candidate.content_projection())

    result = case.store.append_event(candidate)
    reread = case.store.get_event(candidate.event_id, tenant_id=candidate.tenant_id)

    assert result.created
    assert reread == result.event
    assert canonical_json_bytes(result.event.candidate.content_projection()) == (
        expected_content_bytes
    )
    assert result.event.content_checksum == expected_content_checksum
    assert result.event.record_checksum == checksum_for(
        result.event.record_projection()
    )
    result.event.verify_integrity()

    normalized = StoredEvent(
        result.event.candidate,
        observed_at=NORMALIZED_OBSERVED_AT,
        stream_sequence=result.event.stream_sequence,
    )
    assert normalized.record_checksum == checksum_for(normalized.record_projection())


def test_conformance_duplicate_is_idempotent_and_collision_is_typed(
    event_store_case: EventStoreCase,
) -> None:
    case = event_store_case
    candidate = _candidate(case.scope, index=1)

    first = case.store.append_event(candidate)
    duplicate = case.store.append_event(candidate)

    assert first.created
    assert not duplicate.created
    assert duplicate.pending_delivery_count == 0
    assert duplicate.event.to_dict() == first.event.to_dict()
    with pytest.raises(EventIdentityCollisionError):
        case.store.append_event(replace(candidate, payload={"changed": True}))

    second = case.store.append_event(_candidate(case.scope, index=2))
    assert second.event.stream_sequence == 2


def test_conformance_tenant_scope_is_exact_and_sequence_is_per_stream_scope(
    event_store_case: EventStoreCase,
) -> None:
    case = event_store_case
    stream_id = f"{case.scope}:shared-stream"
    tenant_a = f"{case.scope}:tenant-a"
    tenant_b = f"{case.scope}:tenant-b"
    first = case.store.append_event(
        _candidate(
            case.scope,
            index=1,
            stream_id=stream_id,
            tenant_id=tenant_a,
        )
    )
    second = case.store.append_event(
        _candidate(
            case.scope,
            index=2,
            stream_id=stream_id,
            tenant_id=tenant_b,
        )
    )
    unscoped = case.store.append_event(
        _candidate(
            case.scope,
            index=3,
            stream_id=stream_id,
            tenant_id=None,
        )
    )

    assert first.event.stream_sequence == 1
    assert second.event.stream_sequence == 1
    assert unscoped.event.stream_sequence == 1
    assert case.store.get_event(first.event.event_id, tenant_id=tenant_b) is None
    assert case.store.get_event(first.event.event_id) is None
    assert case.store.get_event(unscoped.event.event_id) == unscoped.event
    assert case.store.get_stream_high_watermark(
        stream_id,
        tenant_id=tenant_a,
    ) == 1


def test_conformance_ordered_snapshot_read_and_filter_pagination(
    event_store_case: EventStoreCase,
) -> None:
    case = event_store_case
    for index, event_type in (
        (1, "io.newsroom.test.match"),
        (2, "io.newsroom.test.skip"),
        (3, "io.newsroom.test.match"),
    ):
        case.store.append_event(
            _candidate(case.scope, index=index, event_type=event_type)
        )
    request = StreamReadRequest(
        stream_id=_stream_id(case.scope),
        tenant_id=_tenant_id(case.scope),
        event_types=frozenset({"io.newsroom.test.match"}),
        limit=1,
    )
    first = case.store.read_stream(request)
    assert [event.stream_sequence for event in first.events] == [1]
    assert first.high_watermark == 3
    assert first.next_cursor is not None

    case.store.append_event(
        _candidate(
            case.scope,
            index=4,
            event_type="io.newsroom.test.match",
        )
    )
    second = case.store.read_stream(
        StreamReadRequest(
            stream_id=request.stream_id,
            tenant_id=request.tenant_id,
            event_types=request.event_types,
            cursor=first.next_cursor,
            limit=10,
        )
    )
    assert [event.stream_sequence for event in second.events] == [3]
    assert second.high_watermark == 3
    assert second.next_cursor is None


def test_conformance_append_and_matching_outbox_commit_or_rollback_together(
    event_store_case: EventStoreCase,
) -> None:
    case = event_store_case
    matching = DurableSubscription(
        subscription_id=f"{case.scope}:matching",
        subscription_version=1,
        consumer_id=f"{case.scope}:matching-consumer",
        event_filter=SubscriptionFilter(
            event_types=frozenset({"io.newsroom.test.match"})
        ),
        tenant_id=_tenant_id(case.scope),
    )
    nonmatching = DurableSubscription(
        subscription_id=f"{case.scope}:nonmatching",
        subscription_version=1,
        consumer_id=f"{case.scope}:nonmatching-consumer",
        event_filter=SubscriptionFilter(
            event_types=frozenset({"io.newsroom.test.other"})
        ),
        tenant_id=_tenant_id(case.scope),
    )
    case.store.register_subscription(matching)
    case.store.register_subscription(nonmatching)
    candidate = _candidate(
        case.scope,
        index=1,
        event_type="io.newsroom.test.match",
    )

    with case.store.unit_of_work() as transaction:
        staged = transaction.append_event(candidate)
        assert staged.pending_delivery_count == 1

    assert case.store.get_event(candidate.event_id, tenant_id=candidate.tenant_id) is None
    assert case.store.get_stream_high_watermark(
        candidate.stream_id,
        tenant_id=candidate.tenant_id,
    ) is None
    assert case.store.list_deliveries(
        DeliveryQuery(tenant_id=candidate.tenant_id)
    ).records == ()

    committed = case.store.append_event(candidate)
    deliveries = case.store.list_deliveries(
        DeliveryQuery(tenant_id=candidate.tenant_id)
    ).records
    assert committed.event.stream_sequence == 1
    assert committed.pending_delivery_count == 1
    assert [(delivery.subscription_id, delivery.event_id) for delivery in deliveries] == [
        (matching.subscription_id, candidate.event_id)
    ]


def test_conformance_subscription_versions_keep_independent_start_boundaries(
    event_store_case: EventStoreCase,
) -> None:
    case = event_store_case
    first = case.store.append_event(_candidate(case.scope, index=1)).event
    second = case.store.append_event(_candidate(case.scope, index=2)).event
    subscription_id = f"{case.scope}:versioned"
    starts = (
        (1, SubscriptionStart(SubscriptionStartPolicy.EARLIEST)),
        (2, SubscriptionStart(SubscriptionStartPolicy.LATEST)),
        (
            3,
            SubscriptionStart(
                SubscriptionStartPolicy.AT_SEQUENCE,
                start_sequence=2,
            ),
        ),
    )
    subscriptions = tuple(
        case.store.register_subscription(
            DurableSubscription(
                subscription_id=subscription_id,
                subscription_version=version,
                consumer_id=f"{case.scope}:consumer:{version}",
                start=start,
                tenant_id=_tenant_id(case.scope),
            )
        )
        for version, start in starts
    )
    third = case.store.append_event(_candidate(case.scope, index=3)).event

    expected = {
        1: [first.event_id, second.event_id, third.event_id],
        2: [third.event_id],
        3: [second.event_id, third.event_id],
    }
    for subscription in subscriptions:
        deliveries = case.store.list_deliveries(
            DeliveryQuery(
                subscription_id=subscription.subscription_id,
                subscription_version=subscription.subscription_version,
                tenant_id=subscription.tenant_id,
            )
        ).records
        assert [delivery.event_id for delivery in deliveries] == expected[
            subscription.subscription_version
        ]

    claim_at = case.now()
    claimed = case.store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=subscription_id,
            subscription_version=1,
            lease_owner=f"{case.scope}:version-worker",
            requested_at=claim_at,
            limit=1,
        )
    )[0]
    case.store.settle_delivery(
        DeliverySettlement(
            lease=claimed.lease,
            target_state=DeliveryState.ACKED,
            settled_at=claim_at + timedelta(seconds=1),
        )
    )
    assert case.store.get_checkpoint(
        CheckpointKey(
            subscription_id=subscription_id,
            subscription_version=1,
            stream_id=first.stream_id,
            tenant_id=first.tenant_id,
        )
    ) is not None
    assert case.store.get_checkpoint(
        CheckpointKey(
            subscription_id=subscription_id,
            subscription_version=3,
            stream_id=first.stream_id,
            tenant_id=first.tenant_id,
        )
    ) is None


def test_conformance_pause_resume_and_retirement_drain_without_later_work(
    event_store_case: EventStoreCase,
) -> None:
    case = event_store_case
    definition = DurableSubscription(
        subscription_id=f"{case.scope}:lifecycle",
        subscription_version=1,
        consumer_id=f"{case.scope}:lifecycle-consumer",
        tenant_id=_tenant_id(case.scope),
    )
    registered = case.store.register_subscription(definition)
    changed_at = registered.updated_at or case.now()
    paused = case.store.set_subscription_status(
        registered.key,
        SubscriptionStatus.PAUSED,
        changed_at=changed_at + timedelta(seconds=1),
        reason="maintenance",
    )
    assert case.store.register_subscription(definition) == paused
    first = case.store.append_event(_candidate(case.scope, index=1)).event
    second = case.store.append_event(_candidate(case.scope, index=2)).event
    assert case.store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=registered.subscription_id,
            subscription_version=1,
            lease_owner=f"{case.scope}:paused-worker",
            requested_at=case.now(),
            limit=1,
        )
    ) == ()

    resumed = case.store.set_subscription_status(
        registered.key,
        SubscriptionStatus.ACTIVE,
        changed_at=changed_at + timedelta(seconds=2),
        reason="maintenance complete",
    )
    assert resumed.status is SubscriptionStatus.ACTIVE
    first_claim_at = case.now()
    first_claim = case.store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=registered.subscription_id,
            subscription_version=1,
            lease_owner=f"{case.scope}:active-worker",
            requested_at=first_claim_at,
            limit=1,
        )
    )[0]
    assert first_claim.event.event_id == first.event_id
    case.store.settle_delivery(
        DeliverySettlement(
            lease=first_claim.lease,
            target_state=DeliveryState.ACKED,
            settled_at=first_claim_at + timedelta(seconds=1),
        )
    )

    retired = case.store.set_subscription_status(
        registered.key,
        SubscriptionStatus.RETIRED,
        changed_at=changed_at + timedelta(seconds=3),
        reason="superseded",
    )
    assert retired.status is SubscriptionStatus.RETIRED
    later = case.store.append_event(_candidate(case.scope, index=3)).event
    second_claim_at = case.now()
    second_claim = case.store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=registered.subscription_id,
            subscription_version=1,
            lease_owner=f"{case.scope}:retirement-drain-worker",
            requested_at=second_claim_at,
            limit=1,
        )
    )[0]
    assert second_claim.event.event_id == second.event_id
    case.store.settle_delivery(
        DeliverySettlement(
            lease=second_claim.lease,
            target_state=DeliveryState.ACKED,
            settled_at=second_claim_at + timedelta(seconds=1),
        )
    )
    assert case.store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=registered.subscription_id,
            subscription_version=1,
            lease_owner=f"{case.scope}:retirement-drain-worker",
            requested_at=case.now(),
            limit=1,
        )
    ) == ()
    deliveries = case.store.list_deliveries(
        DeliveryQuery(
            subscription_id=registered.subscription_id,
            subscription_version=1,
            tenant_id=registered.tenant_id,
        )
    ).records
    assert [delivery.event_id for delivery in deliveries] == [
        first.event_id,
        second.event_id,
    ]
    assert later.event_id not in {delivery.event_id for delivery in deliveries}
    assert case.store.pending_delivery_stats(registered.key).pending_count == 0

    with pytest.raises(ValueError, match="RETIRED"):
        case.store.register_subscription(
            replace(
                definition,
                subscription_id=f"{case.scope}:initially-retired",
                status=SubscriptionStatus.RETIRED,
            )
        )


def test_conformance_retirement_cancellation_is_bounded_audited_and_fenced(
    event_store_case: EventStoreCase,
) -> None:
    case = event_store_case
    subscription = case.store.register_subscription(
        DurableSubscription(
            subscription_id=f"{case.scope}:retirement-cancel",
            subscription_version=1,
            consumer_id=f"{case.scope}:retirement-cancel-consumer",
            tenant_id=_tenant_id(case.scope),
        )
    )
    events = tuple(
        case.store.append_event(_candidate(case.scope, index=index)).event
        for index in range(1, 5)
    )
    claim = case.store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=subscription.subscription_id,
            subscription_version=subscription.subscription_version,
            lease_owner=f"{case.scope}:retirement-cancel-worker",
            requested_at=case.now(),
            limit=1,
        )
    )[0]
    retired_at = (subscription.updated_at or case.now()) + timedelta(seconds=1)
    retired = case.store.set_subscription_status(
        subscription.key,
        SubscriptionStatus.RETIRED,
        changed_at=retired_at,
        reason="consumer version permanently withdrawn",
    )
    assert retired.status is SubscriptionStatus.RETIRED

    first_request = RetirementCancellationRequest(
        cancellation_id=f"{case.scope}:retirement-cancellation:1",
        subscription=subscription.key,
        requested_at=max(case.now(), retired_at),
        operator_id=f"{case.scope}:operator",
        operator_reason="terminally cancel bounded retired work",
        authorization_evidence_ref=f"authz:{case.scope}:retirement-cancel",
        tenant_id=subscription.tenant_id,
        limit=2,
    )
    first = case.store.cancel_retired_subscription(first_request)
    exact_retry = case.store.cancel_retired_subscription(first_request)
    reauthorized_retry = case.store.cancel_retired_subscription(
        replace(
            first_request,
            requested_at=first_request.requested_at + timedelta(seconds=1),
            authorization_evidence_ref=(
                first_request.authorization_evidence_ref + ":reauthorized"
            ),
        )
    )

    assert exact_retry == first
    assert reauthorized_retry == first
    assert first.cancelled_count == 2
    assert first.remaining_nonterminal_count == 2
    assert first.completed is False
    assert [item.stream_sequence for item in first.items] == [1, 2]
    assert [item.previous_state for item in first.items] == [
        DeliveryState.CLAIMED,
        DeliveryState.PENDING,
    ]
    assert [item.previous_attempt_count for item in first.items] == [1, 0]
    assert all(item.terminal_state is DeliveryState.DROPPED for item in first.items)
    assert case.store.get_retirement_cancellation_report(
        first.cancellation_id,
        tenant_id=subscription.tenant_id,
    ) == first
    assert case.store.get_retirement_cancellation_report(
        first.cancellation_id,
        tenant_id=f"{case.scope}:another-tenant",
    ) is None

    with pytest.raises(EventRetirementCancellationCollisionError):
        case.store.cancel_retired_subscription(
            replace(first_request, operator_reason="different command identity")
        )
    with pytest.raises(EventStaleLeaseError):
        case.store.settle_delivery(
            DeliverySettlement(
                lease=claim.lease,
                target_state=DeliveryState.ACKED,
                settled_at=first.cancelled_at + timedelta(seconds=1),
            )
        )

    checkpoint = case.store.get_checkpoint(
        CheckpointKey(
            subscription_id=subscription.subscription_id,
            subscription_version=subscription.subscription_version,
            stream_id=events[0].stream_id,
            tenant_id=subscription.tenant_id,
        ),
        tenant_id=subscription.tenant_id,
    )
    assert checkpoint is not None
    assert checkpoint.highest_contiguous_terminal_sequence == 2
    assert checkpoint.terminal_disposition is DeliveryState.DROPPED

    second_request = RetirementCancellationRequest(
        cancellation_id=f"{case.scope}:retirement-cancellation:2",
        subscription=subscription.key,
        requested_at=first.cancelled_at,
        operator_id=f"{case.scope}:operator",
        operator_reason="finish terminal cancellation of retired work",
        authorization_evidence_ref=f"authz:{case.scope}:retirement-cancel",
        tenant_id=subscription.tenant_id,
    )
    second = case.store.cancel_retired_subscription(second_request)
    assert second.cancelled_count == 2
    assert second.remaining_nonterminal_count == 0
    assert second.completed is True

    final_deliveries = case.store.list_deliveries(
        DeliveryQuery(
            subscription_id=subscription.subscription_id,
            subscription_version=subscription.subscription_version,
            tenant_id=subscription.tenant_id,
        )
    ).records
    assert len(final_deliveries) == 4
    assert all(
        delivery.state is DeliveryState.DROPPED
        and delivery.reason_class == "subscription_retired"
        and delivery.lease_owner is None
        and delivery.lease_generation is None
        and delivery.lease_expires_at is None
        for delivery in final_deliveries
    )
    assert [delivery.attempt_count for delivery in final_deliveries] == [1, 1, 1, 1]
    final_checkpoint = case.store.get_checkpoint(
        CheckpointKey(
            subscription_id=subscription.subscription_id,
            subscription_version=subscription.subscription_version,
            stream_id=events[0].stream_id,
            tenant_id=subscription.tenant_id,
        ),
        tenant_id=subscription.tenant_id,
    )
    assert final_checkpoint is not None
    assert final_checkpoint.highest_contiguous_terminal_sequence == 4
    assert case.store.list_dead_letters(
        DeadLetterQuery(
            subscription_id=subscription.subscription_id,
            subscription_version=subscription.subscription_version,
            tenant_id=subscription.tenant_id,
        )
    ).records == ()
    assert case.store.get_inbox_entry(
        InboxKey(events[0].event_id, f"{case.scope}:unrelated-effect"),
        tenant_id=subscription.tenant_id,
    ) is None

    later = case.store.append_event(_candidate(case.scope, index=5)).event
    after_retirement = case.store.list_deliveries(
        DeliveryQuery(
            subscription_id=subscription.subscription_id,
            subscription_version=subscription.subscription_version,
            tenant_id=subscription.tenant_id,
        )
    ).records
    assert later.event_id not in {delivery.event_id for delivery in after_retirement}


def test_conformance_retirement_cancellation_uses_byte_stable_stream_order(
    event_store_case: EventStoreCase,
) -> None:
    case = event_store_case
    subscription = case.store.register_subscription(
        DurableSubscription(
            subscription_id=f"{case.scope}:retirement-order",
            subscription_version=1,
            consumer_id=f"{case.scope}:retirement-order-consumer",
            tenant_id=_tenant_id(case.scope),
        )
    )
    stream_ids = (
        f"{case.scope}:stream:a",
        f"{case.scope}:stream:Z",
        f"{case.scope}:stream:\u00e9",
        f"{case.scope}:stream:\u03a9",
    )
    for index, stream_id in enumerate(reversed(stream_ids), start=100):
        case.store.append_event(
            _candidate(case.scope, index=index, stream_id=stream_id)
        )
    retired_at = (subscription.updated_at or case.now()) + timedelta(seconds=1)
    case.store.set_subscription_status(
        subscription.key,
        SubscriptionStatus.RETIRED,
        changed_at=retired_at,
        reason="retire multi-stream ordering fixture",
    )

    report = case.store.cancel_retired_subscription(
        RetirementCancellationRequest(
            cancellation_id=f"{case.scope}:retirement-order-command",
            subscription=subscription.key,
            requested_at=max(case.now(), retired_at),
            operator_id=f"{case.scope}:operator",
            operator_reason="cancel streams in byte-stable order",
            authorization_evidence_ref=f"authz:{case.scope}:retirement-order",
            tenant_id=subscription.tenant_id,
            limit=len(stream_ids),
        )
    )

    expected = sorted(stream_ids, key=lambda value: value.encode("utf-8"))
    assert [item.stream_id for item in report.items] == expected
    assert case.store.get_retirement_cancellation_report(
        report.cancellation_id,
        tenant_id=subscription.tenant_id,
    ) == report


def test_conformance_retirement_cancellation_never_rewinds_for_late_repair(
    event_store_case: EventStoreCase,
) -> None:
    case = event_store_case
    subscription = case.store.register_subscription(
        DurableSubscription(
            subscription_id=f"{case.scope}:retirement-cancel-repair",
            subscription_version=1,
            consumer_id=f"{case.scope}:retirement-cancel-repair-consumer",
            supports_out_of_order_repair=True,
            tenant_id=_tenant_id(case.scope),
        )
    )
    events = tuple(
        case.store.append_event(_candidate(case.scope, index=index)).event
        for index in range(1, 4)
    )
    for index in range(1, 4):
        claim = case.store.claim_deliveries(
            DeliveryClaimRequest(
                subscription_id=subscription.subscription_id,
                subscription_version=subscription.subscription_version,
                lease_owner=f"{case.scope}:repair-frontier-worker",
                requested_at=case.now(),
                limit=1,
            )
        )[0]
        case.store.settle_delivery(
            DeliverySettlement(
                lease=claim.lease,
                target_state=DeliveryState.ACKED,
                settled_at=case.now() + timedelta(seconds=index),
            )
        )
    before = case.store.get_checkpoint(
        CheckpointKey(
            subscription_id=subscription.subscription_id,
            subscription_version=subscription.subscription_version,
            stream_id=events[0].stream_id,
            tenant_id=subscription.tenant_id,
        ),
        tenant_id=subscription.tenant_id,
    )
    assert before is not None
    assert before.highest_contiguous_terminal_sequence == 3

    redelivery = case.store.begin_redelivery(
        RedeliveryRequest(
            redelivery_id=f"{case.scope}:retirement-cancel-repair-redelivery",
            subscription=subscription.key,
            source_stream_id=events[0].stream_id,
            from_sequence=1,
            through_sequence=1,
            requested_at=case.now() + timedelta(seconds=4),
            operator_id=f"{case.scope}:operator",
            operator_reason="verify repaired event again",
            authorization_evidence_ref=f"authz:{case.scope}:repair-redelivery",
            tenant_id=subscription.tenant_id,
        )
    )
    assert redelivery.items[0].delivery_generation == 2
    retired_at = case.now() + timedelta(seconds=5)
    case.store.set_subscription_status(
        subscription.key,
        SubscriptionStatus.RETIRED,
        changed_at=retired_at,
        reason="late repair subscription retired",
    )
    cancellation = case.store.cancel_retired_subscription(
        RetirementCancellationRequest(
            cancellation_id=f"{case.scope}:retirement-cancel-repair-command",
            subscription=subscription.key,
            requested_at=retired_at,
            operator_id=f"{case.scope}:operator",
            operator_reason="terminally cancel remaining late repair",
            authorization_evidence_ref=f"authz:{case.scope}:repair-cancel",
            tenant_id=subscription.tenant_id,
        )
    )

    assert cancellation.cancelled_count == 1
    assert cancellation.items[0].delivery_generation == 2
    after = case.store.get_checkpoint(
        CheckpointKey(
            subscription_id=subscription.subscription_id,
            subscription_version=subscription.subscription_version,
            stream_id=events[0].stream_id,
            tenant_id=subscription.tenant_id,
        ),
        tenant_id=subscription.tenant_id,
    )
    assert after is not None
    assert after.highest_contiguous_terminal_sequence == 3
    assert after.checkpoint_version == before.checkpoint_version


def test_conformance_retired_subscription_cannot_reopen_through_dlq_requeue(
    event_store_case: EventStoreCase,
) -> None:
    case = event_store_case
    subscription = case.store.register_subscription(
        DurableSubscription(
            subscription_id=f"{case.scope}:retired-dlq-requeue",
            subscription_version=1,
            consumer_id=f"{case.scope}:retired-dlq-requeue-consumer",
            supports_out_of_order_repair=True,
            tenant_id=_tenant_id(case.scope),
        )
    )
    event = case.store.append_event(_candidate(case.scope, index=1)).event
    claimed_at = case.now()
    claim = case.store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=subscription.subscription_id,
            subscription_version=subscription.subscription_version,
            lease_owner=f"{case.scope}:retired-dlq-worker",
            requested_at=claimed_at,
            limit=1,
        )
    )[0]
    dead = case.store.settle_delivery(
        DeliverySettlement(
            lease=claim.lease,
            target_state=DeliveryState.DEAD_LETTER,
            settled_at=claimed_at + timedelta(seconds=1),
            reason_class="permanent_failure",
        )
    )
    assert dead.dead_letter_id is not None
    retired_at = claimed_at + timedelta(seconds=2)
    case.store.set_subscription_status(
        subscription.key,
        SubscriptionStatus.RETIRED,
        changed_at=retired_at,
        reason="retire after permanent failure",
    )
    cancellation = case.store.cancel_retired_subscription(
        RetirementCancellationRequest(
            cancellation_id=f"{case.scope}:retired-dlq-cancellation",
            subscription=subscription.key,
            requested_at=retired_at,
            operator_id=f"{case.scope}:operator",
            operator_reason="confirm retired subscription is terminal",
            authorization_evidence_ref=f"authz:{case.scope}:retired-dlq",
            tenant_id=subscription.tenant_id,
        )
    )
    assert cancellation.completed
    assert cancellation.cancelled_count == 0

    with pytest.raises(EventRetirementCancellationError):
        case.store.requeue_dead_letter(
            DeadLetterAction(
                dead_letter_id=dead.dead_letter_id,
                operator_id=f"{case.scope}:operator",
                reason="must not reopen retired work",
                requested_at=retired_at + timedelta(seconds=1),
                idempotency_ready=True,
            )
        )

    deliveries = case.store.list_deliveries(
        DeliveryQuery(
            subscription_id=subscription.subscription_id,
            subscription_version=subscription.subscription_version,
            tenant_id=subscription.tenant_id,
        )
    ).records
    assert len(deliveries) == 1
    assert deliveries[0].event_id == event.event_id
    assert deliveries[0].state is DeliveryState.DEAD_LETTER
    assert case.store.get_dead_letter(
        dead.dead_letter_id,
        tenant_id=subscription.tenant_id,
    ).disposition is DeadLetterDisposition.OPEN


@pytest.mark.parametrize(
    "start",
    (
        SubscriptionStart(SubscriptionStartPolicy.EARLIEST),
        SubscriptionStart(SubscriptionStartPolicy.LATEST),
        SubscriptionStart(
            SubscriptionStartPolicy.AT_SEQUENCE,
            start_sequence=1,
        ),
    ),
    ids=("earliest", "latest", "at-sequence"),
)
def test_conformance_registration_and_publication_have_one_linearized_boundary(
    event_store_case: EventStoreCase,
    start: SubscriptionStart,
) -> None:
    case = event_store_case
    subscription = DurableSubscription(
        subscription_id=f"{case.scope}:registration-race:{start.policy.value}",
        subscription_version=1,
        consumer_id=f"{case.scope}:registration-race-consumer",
        start=start,
        tenant_id=_tenant_id(case.scope),
    )
    candidate = _candidate(case.scope, index=1)
    barrier = Barrier(2)

    def register() -> DurableSubscription:
        barrier.wait(timeout=15)
        return case.store.register_subscription(subscription)

    def publish() -> StoredEvent:
        barrier.wait(timeout=15)
        return case.store.append_event(candidate).event

    with ThreadPoolExecutor(max_workers=2) as executor:
        registered_future = executor.submit(register)
        published_future = executor.submit(publish)
        registered = registered_future.result(timeout=15)
        published = published_future.result(timeout=15)

    state = case.store.get_subscription_stream_state(
        registered.key,
        published.stream_id,
        tenant_id=published.tenant_id,
    )
    assert state is not None
    deliveries = case.store.list_deliveries(
        DeliveryQuery(
            subscription_id=registered.subscription_id,
            subscription_version=1,
            tenant_id=registered.tenant_id,
        )
    ).records
    if start.policy is SubscriptionStartPolicy.LATEST:
        expected = [] if state.registration_watermark == 1 else [published.event_id]
    else:
        expected = [published.event_id]
    assert [delivery.event_id for delivery in deliveries] == expected


def test_conformance_retirement_and_publication_share_the_watermark_boundary(
    event_store_case: EventStoreCase,
) -> None:
    case = event_store_case
    seed = case.store.append_event(_candidate(case.scope, index=1)).event
    subscription = case.store.register_subscription(
        DurableSubscription(
            subscription_id=f"{case.scope}:retirement-race",
            subscription_version=1,
            consumer_id=f"{case.scope}:retirement-race-consumer",
            tenant_id=_tenant_id(case.scope),
        )
    )
    candidate = _candidate(case.scope, index=2)
    barrier = Barrier(2)

    def retire() -> DurableSubscription:
        barrier.wait(timeout=15)
        return case.store.set_subscription_status(
            subscription.key,
            SubscriptionStatus.RETIRED,
            changed_at=(subscription.updated_at or case.now())
            + timedelta(seconds=1),
            reason="race cutover",
        )

    def publish() -> StoredEvent:
        barrier.wait(timeout=15)
        return case.store.append_event(candidate).event

    with ThreadPoolExecutor(max_workers=2) as executor:
        retired_future = executor.submit(retire)
        published_future = executor.submit(publish)
        retired_future.result(timeout=15)
        published = published_future.result(timeout=15)

    state = case.store.get_subscription_stream_state(
        subscription.key,
        seed.stream_id,
        tenant_id=seed.tenant_id,
    )
    assert state is not None
    assert state.retirement_watermark in {1, 2}
    deliveries = case.store.list_deliveries(
        DeliveryQuery(
            subscription_id=subscription.subscription_id,
            subscription_version=1,
            tenant_id=subscription.tenant_id,
        )
    ).records
    published_deliveries = [
        delivery for delivery in deliveries if delivery.event_id == published.event_id
    ]
    assert bool(published_deliveries) is (state.retirement_watermark == 2)


def test_conformance_registration_backfill_capacity_failure_is_atomic(
    event_store_case: EventStoreCase,
) -> None:
    case = event_store_case
    for index in range(1, 4):
        case.store.append_event(_candidate(case.scope, index=index))
    subscription = DurableSubscription(
        subscription_id=f"{case.scope}:backfill-capacity",
        subscription_version=1,
        consumer_id=f"{case.scope}:backfill-capacity-consumer",
        limits=DeliveryLimits(
            batch_size=1,
            max_in_flight=1,
            max_concurrency=1,
            pending_warning_threshold=1,
            pending_hard_limit=2,
        ),
        tenant_id=_tenant_id(case.scope),
    )

    with pytest.raises(EventStoreCapacityError):
        case.store.register_subscription(subscription)

    assert case.store.get_subscription(subscription.key) is None
    assert case.store.list_deliveries(
        DeliveryQuery(
            subscription_id=subscription.subscription_id,
            subscription_version=1,
            tenant_id=subscription.tenant_id,
        )
    ).records == ()


def test_conformance_backfill_delivery_uses_store_time_not_future_metadata(
    event_store_case: EventStoreCase,
) -> None:
    case = event_store_case
    event = case.store.append_event(_candidate(case.scope, index=1)).event
    future_created_at = case.now() + timedelta(days=1)
    subscription = case.store.register_subscription(
        DurableSubscription(
            subscription_id=f"{case.scope}:future-registration-time",
            subscription_version=1,
            consumer_id=f"{case.scope}:future-registration-consumer",
            tenant_id=_tenant_id(case.scope),
            created_at=future_created_at,
            updated_at=future_created_at,
        )
    )

    claimed = case.store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=subscription.subscription_id,
            subscription_version=1,
            lease_owner=f"{case.scope}:future-registration-worker",
            requested_at=case.now(),
            limit=1,
        )
    )[0]

    assert claimed.event.event_id == event.event_id
    assert claimed.lease.lease_started_at is not None
    assert claimed.lease.lease_started_at < claimed.lease.lease_expires_at


def test_conformance_at_sequence_allows_one_past_end_and_rejects_later_future(
    event_store_case: EventStoreCase,
) -> None:
    case = event_store_case
    case.store.append_event(_candidate(case.scope, index=1))
    valid = case.store.register_subscription(
        DurableSubscription(
            subscription_id=f"{case.scope}:one-past-end",
            subscription_version=1,
            consumer_id=f"{case.scope}:one-past-consumer",
            start=SubscriptionStart(
                SubscriptionStartPolicy.AT_SEQUENCE,
                start_sequence=2,
            ),
            tenant_id=_tenant_id(case.scope),
        )
    )
    assert case.store.list_deliveries(
        DeliveryQuery(
            subscription_id=valid.subscription_id,
            subscription_version=1,
            tenant_id=_tenant_id(case.scope),
        )
    ).records == ()
    second = case.store.append_event(_candidate(case.scope, index=2))
    valid_deliveries = case.store.list_deliveries(
        DeliveryQuery(
            subscription_id=valid.subscription_id,
            subscription_version=1,
            tenant_id=_tenant_id(case.scope),
        )
    ).records
    assert [delivery.event_id for delivery in valid_deliveries] == [
        second.event.event_id
    ]

    invalid = DurableSubscription(
        subscription_id=f"{case.scope}:far-future",
        subscription_version=1,
        consumer_id=f"{case.scope}:far-future-consumer",
        start=SubscriptionStart(
            SubscriptionStartPolicy.AT_SEQUENCE,
            start_sequence=4,
        ),
        tenant_id=_tenant_id(case.scope),
    )
    with pytest.raises(EventSubscriptionPositionError) as failure:
        case.store.register_subscription(invalid)
    assert failure.value.requested_sequence == 4
    assert failure.value.maximum_sequence == 3
    assert case.store.get_subscription(invalid.key) is None


def test_conformance_at_sequence_without_stream_waits_for_exact_future_position(
    event_store_case: EventStoreCase,
) -> None:
    case = event_store_case
    subscription = case.store.register_subscription(
        DurableSubscription(
            subscription_id=f"{case.scope}:future-stream",
            subscription_version=1,
            consumer_id=f"{case.scope}:future-stream-consumer",
            start=SubscriptionStart(
                SubscriptionStartPolicy.AT_SEQUENCE,
                start_sequence=2,
            ),
            tenant_id=_tenant_id(case.scope),
        )
    )
    first = case.store.append_event(_candidate(case.scope, index=1))
    assert case.store.list_deliveries(
        DeliveryQuery(
            subscription_id=subscription.subscription_id,
            subscription_version=1,
            tenant_id=_tenant_id(case.scope),
        )
    ).records == ()
    assert case.store.get_subscription_stream_state(
        subscription.key,
        first.event.stream_id,
        tenant_id=first.event.tenant_id,
    ) is None

    second = case.store.append_event(_candidate(case.scope, index=2))
    deliveries = case.store.list_deliveries(
        DeliveryQuery(
            subscription_id=subscription.subscription_id,
            subscription_version=1,
            tenant_id=_tenant_id(case.scope),
        )
    ).records
    assert [delivery.event_id for delivery in deliveries] == [
        second.event.event_id
    ]


def test_conformance_replay_requires_running_before_success(
    event_store_case: EventStoreCase,
) -> None:
    case = event_store_case
    event = case.store.append_event(_candidate(case.scope, index=1)).event
    started_at = case.now()
    pending = case.store.begin_replay(
        ReplayStartRequest(
            replay_id=f"{case.scope}:replay",
            mode=ReplayMode.REBUILD_STATE,
            source_stream_id=event.stream_id,
            requested_at=started_at,
            tenant_id=event.tenant_id,
        )
    )
    direct_success = replace(
        pending,
        status=ReplayStatus.SUCCEEDED,
        to_sequence=event.stream_sequence,
        result_checksum="sha256:" + "3" * 64,
        finished_at=started_at + timedelta(seconds=1),
    )
    with pytest.raises(EventStoreError):
        case.store.update_replay_report(direct_success)
    running = case.store.update_replay_report(
        replace(pending, status=ReplayStatus.RUNNING)
    )
    completed = case.store.update_replay_report(
        replace(
            running,
            status=ReplayStatus.SUCCEEDED,
            to_sequence=event.stream_sequence,
            result_checksum="sha256:" + "3" * 64,
            finished_at=started_at + timedelta(seconds=1),
        )
    )
    assert completed.status is ReplayStatus.SUCCEEDED
    assert case.store.get_replay_report(
        completed.replay_id,
        tenant_id=event.tenant_id,
    ) == completed


def test_conformance_capacity_and_stale_lease_errors_are_typed_and_atomic(
    event_store_case: EventStoreCase,
) -> None:
    case = event_store_case
    subscription = DurableSubscription(
        subscription_id=f"{case.scope}:bounded",
        subscription_version=1,
        consumer_id=f"{case.scope}:bounded-consumer",
        limits=DeliveryLimits(
            batch_size=1,
            max_in_flight=1,
            max_concurrency=1,
            pending_warning_threshold=1,
            pending_hard_limit=2,
        ),
        tenant_id=_tenant_id(case.scope),
    )
    case.store.register_subscription(subscription)
    case.store.append_event(_candidate(case.scope, index=1))
    case.store.append_event(_candidate(case.scope, index=2))

    with pytest.raises(EventStoreCapacityError):
        case.store.append_event(_candidate(case.scope, index=3))

    assert case.store.get_event(
        _event_id(case.scope, 3),
        tenant_id=_tenant_id(case.scope),
    ) is None
    assert case.store.get_stream_high_watermark(
        _stream_id(case.scope),
        tenant_id=_tenant_id(case.scope),
    ) == 2
    stats = case.store.pending_delivery_stats(subscription.key)
    assert stats.pending_count == 2
    assert stats.lag == 2
    assert stats.late_repair_pending_count == 0
    assert stats.warning_threshold_reached
    assert stats.capacity_remaining == 0
    assert stats.oldest_pending_at is not None
    assert stats.oldest_pending_age_seconds is not None
    assert stats.oldest_pending_age_seconds >= 0

    claim = case.store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=subscription.subscription_id,
            subscription_version=subscription.subscription_version,
            lease_owner=f"{case.scope}:worker",
            requested_at=case.now(),
            limit=1,
        )
    )[0]
    assert claim.lease.lease_started_at is not None
    assert claim.lease.lease_started_at < claim.lease.lease_expires_at
    with pytest.raises(EventStaleLeaseError):
        renewed_at = case.now()
        case.store.renew_delivery_lease(
            replace(claim.lease, lease_owner=f"{case.scope}:stale-worker"),
            renewed_at=renewed_at,
            lease_duration_seconds=30,
        )
    assert case.store.get_delivery(
        claim.delivery.delivery_id,
        tenant_id=_tenant_id(case.scope),
    ).state is DeliveryState.CLAIMED
    renewed = case.store.renew_delivery_lease(
        claim.lease,
        renewed_at=claim.lease.lease_expires_at + timedelta(days=1),
        lease_duration_seconds=30,
    )
    assert renewed.lease_started_at is not None
    case.store.settle_delivery(
        DeliverySettlement(
            lease=renewed,
            target_state=DeliveryState.ACKED,
            settled_at=renewed.lease_expires_at + timedelta(days=1),
        )
    )
    recovered = case.store.append_event(_candidate(case.scope, index=3))
    assert recovered.event.stream_sequence == 3
    assert recovered.pending_delivery_count == 1


def test_conformance_max_concurrency_is_a_durable_lease_owner_slot(
    event_store_case: EventStoreCase,
) -> None:
    case = event_store_case
    subscription = case.store.register_subscription(
        DurableSubscription(
            subscription_id=f"{case.scope}:concurrency",
            subscription_version=1,
            consumer_id=f"{case.scope}:concurrency-consumer",
            limits=DeliveryLimits(
                batch_size=1,
                max_in_flight=4,
                max_concurrency=1,
                pending_warning_threshold=4,
                pending_hard_limit=8,
            ),
            tenant_id=_tenant_id(case.scope),
        )
    )
    for index in range(1, 4):
        case.store.append_event(
            _candidate(
                case.scope,
                index=index,
                stream_id=f"{case.scope}:concurrency-stream:{index}",
            )
        )
    requested_at = case.now()
    owner_a = f"{case.scope}:worker-a"
    owner_b = f"{case.scope}:worker-b"

    first = case.store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=subscription.subscription_id,
            subscription_version=1,
            lease_owner=owner_a,
            requested_at=requested_at,
            limit=1,
        )
    )
    assert len(first) == 1
    assert case.store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=subscription.subscription_id,
            subscription_version=1,
            lease_owner=owner_b,
            requested_at=requested_at,
            limit=1,
        )
    ) == ()
    second = case.store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=subscription.subscription_id,
            subscription_version=1,
            lease_owner=owner_a,
            requested_at=requested_at,
            limit=1,
        )
    )
    assert len(second) == 1

    for offset, claim in enumerate((*first, *second), start=1):
        case.store.settle_delivery(
            DeliverySettlement(
                lease=claim.lease,
                target_state=DeliveryState.ACKED,
                settled_at=requested_at + timedelta(seconds=offset),
            )
        )
    released = case.store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=subscription.subscription_id,
            subscription_version=1,
            lease_owner=owner_b,
            requested_at=case.now(),
            limit=1,
        )
    )
    assert len(released) == 1


def test_conformance_requeue_capacity_and_lag_keep_late_repair_separate(
    event_store_case: EventStoreCase,
) -> None:
    case = event_store_case
    subscription = case.store.register_subscription(
        DurableSubscription(
            subscription_id=f"{case.scope}:late-repair-capacity",
            subscription_version=1,
            consumer_id=f"{case.scope}:late-repair-consumer",
            limits=DeliveryLimits(
                batch_size=1,
                max_in_flight=1,
                max_concurrency=1,
                pending_warning_threshold=1,
                pending_hard_limit=2,
            ),
            supports_out_of_order_repair=True,
            tenant_id=_tenant_id(case.scope),
        )
    )
    first = case.store.append_event(_candidate(case.scope, index=1)).event
    case.store.append_event(_candidate(case.scope, index=2))
    first_claim_at = case.now()
    first_claim = case.store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=subscription.subscription_id,
            subscription_version=1,
            lease_owner=f"{case.scope}:repair-worker",
            requested_at=first_claim_at,
            limit=1,
        )
    )[0]
    dead = case.store.settle_delivery(
        DeliverySettlement(
            lease=first_claim.lease,
            target_state=DeliveryState.DEAD_LETTER,
            settled_at=first_claim_at + timedelta(seconds=1),
            reason_class="poison",
        )
    )
    assert dead.dead_letter_id is not None
    case.store.append_event(_candidate(case.scope, index=3))
    rejected_action = DeadLetterAction(
        dead_letter_id=dead.dead_letter_id,
        operator_id="operator",
        reason="repair after capacity frees",
        requested_at=case.now(),
        idempotency_ready=True,
    )
    with pytest.raises(EventStoreCapacityError):
        case.store.requeue_dead_letter(rejected_action)
    assert case.store.get_dead_letter(
        dead.dead_letter_id,
        tenant_id=first.tenant_id,
    ).disposition is DeadLetterDisposition.OPEN

    second_claim_at = case.now()
    second_claim = case.store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=subscription.subscription_id,
            subscription_version=1,
            lease_owner=f"{case.scope}:repair-worker",
            requested_at=second_claim_at,
            limit=1,
        )
    )[0]
    case.store.settle_delivery(
        DeliverySettlement(
            lease=second_claim.lease,
            target_state=DeliveryState.ACKED,
            settled_at=second_claim_at + timedelta(seconds=1),
        )
    )
    repaired = case.store.requeue_dead_letter(
        replace(
            rejected_action,
            requested_at=case.now() + timedelta(days=1),
        )
    )
    assert repaired.delivery_generation == 2
    repair_claim = case.store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=subscription.subscription_id,
            subscription_version=1,
            lease_owner=f"{case.scope}:late-repair-worker",
            requested_at=case.now(),
            limit=1,
        )
    )[0]
    assert repair_claim.delivery.delivery_id == repaired.delivery_id
    assert repair_claim.lease.lease_started_at is not None
    stats = case.store.pending_delivery_stats(
        SubscriptionKey(subscription.subscription_id, 1)
    )
    assert stats.pending_count == 2
    assert stats.lag == 1
    assert stats.late_repair_pending_count == 1
    assert stats.warning_threshold_reached
    assert stats.capacity_remaining == 0
    checkpoint = case.store.get_checkpoint(
        CheckpointKey(
            subscription_id=subscription.subscription_id,
            subscription_version=1,
            stream_id=first.stream_id,
            tenant_id=first.tenant_id,
        )
    )
    assert checkpoint is not None
    assert checkpoint.highest_contiguous_terminal_sequence == 2


def test_conformance_retry_at_budget_is_normalized_to_dead_letter(
    event_store_case: EventStoreCase,
) -> None:
    case = event_store_case
    subscription = case.store.register_subscription(
        DurableSubscription(
            subscription_id=f"{case.scope}:retry-budget",
            subscription_version=1,
            consumer_id=f"{case.scope}:retry-consumer",
            retry_policy=RetryPolicy(max_attempts=1),
            tenant_id=_tenant_id(case.scope),
        )
    )
    event = case.store.append_event(_candidate(case.scope, index=1)).event
    requested_at = case.now()
    claim = case.store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=subscription.subscription_id,
            subscription_version=subscription.subscription_version,
            lease_owner=f"{case.scope}:worker",
            requested_at=requested_at,
            limit=1,
        )
    )[0]
    result = case.store.settle_delivery(
        DeliverySettlement(
            lease=claim.lease,
            target_state=DeliveryState.RETRY_WAIT,
            settled_at=requested_at + timedelta(seconds=1),
            reason_class="retryable",
            retry_available_at=requested_at + timedelta(seconds=2),
        )
    )
    assert result.delivery.state is DeliveryState.DEAD_LETTER
    assert result.dead_letter_id is not None
    assert result.checkpoint is not None
    assert result.checkpoint.highest_contiguous_terminal_sequence == (
        event.stream_sequence
    )


def test_conformance_retry_wait_blocks_later_sequence_in_the_same_stream(
    event_store_case: EventStoreCase,
) -> None:
    case = event_store_case
    subscription = case.store.register_subscription(
        DurableSubscription(
            subscription_id=f"{case.scope}:ordered-retry",
            subscription_version=1,
            consumer_id=f"{case.scope}:ordered-retry-consumer",
            tenant_id=_tenant_id(case.scope),
        )
    )
    first = case.store.append_event(_candidate(case.scope, index=1)).event
    case.store.append_event(_candidate(case.scope, index=2))
    requested_at = case.now()
    claimed = case.store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=subscription.subscription_id,
            subscription_version=1,
            lease_owner=f"{case.scope}:ordered-worker",
            requested_at=requested_at,
            limit=1,
        )
    )[0]
    assert claimed.event.event_id == first.event_id
    case.store.settle_delivery(
        DeliverySettlement(
            lease=claimed.lease,
            target_state=DeliveryState.RETRY_WAIT,
            settled_at=requested_at + timedelta(seconds=1),
            retry_available_at=requested_at + timedelta(minutes=1),
            reason_class="transient",
        )
    )

    assert case.store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=subscription.subscription_id,
            subscription_version=1,
            lease_owner=f"{case.scope}:ordered-worker",
            requested_at=case.now(),
            limit=1,
        )
    ) == ()
    assert case.store.get_checkpoint(
        CheckpointKey(
            subscription_id=subscription.subscription_id,
            subscription_version=1,
            stream_id=first.stream_id,
            tenant_id=first.tenant_id,
        )
    ) is None


def test_conformance_inbox_ack_is_required_and_conflicts_are_typed(
    event_store_case: EventStoreCase,
) -> None:
    case = event_store_case
    subscription_id = f"{case.scope}:effect"
    effect_id = f"{case.scope}:effect-id"
    effect = ConsumerEffectContract(
        performs_external_effects=True,
        consumer_effect_id=effect_id,
        idempotency_strategy=EffectIdempotencyStrategy.INBOX_TRANSACTION,
    )
    for version in (1, 2, 3):
        case.store.register_subscription(
            DurableSubscription(
                subscription_id=subscription_id,
                subscription_version=version,
                consumer_id=f"{case.scope}:consumer:{version}",
                effect=effect,
                tenant_id=_tenant_id(case.scope),
            )
        )
    candidate = _candidate(case.scope, index=1)
    appended = case.store.append_event(candidate)
    assert appended.pending_delivery_count == 3

    first_claim_at = case.now()
    first = case.store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=subscription_id,
            subscription_version=1,
            lease_owner=f"{case.scope}:worker:1",
            requested_at=first_claim_at,
            limit=1,
        )
    )[0]
    without_inbox = DeliverySettlement(
        lease=first.lease,
        target_state=DeliveryState.ACKED,
        settled_at=first_claim_at + timedelta(seconds=1),
    )
    with pytest.raises(EventConsumerIdempotencyError):
        case.store.settle_delivery(without_inbox)
    assert case.store.get_delivery(
        first.delivery.delivery_id,
        tenant_id=candidate.tenant_id,
    ).state is DeliveryState.CLAIMED

    result_checksum = "sha256:" + "1" * 64
    first_result = case.store.settle_delivery(
        replace(
            without_inbox,
            inbox_entry=InboxEntry(
                event_id=candidate.event_id,
                consumer_effect_id=effect_id,
                completed_at=first_claim_at + timedelta(seconds=1),
                result_checksum=result_checksum,
            ),
        )
    )
    assert first_result.delivery.state is DeliveryState.ACKED
    assert first_result.inbox_recorded
    persisted_inbox = case.store.get_inbox_entry(
        InboxKey(candidate.event_id, effect_id),
        tenant_id=candidate.tenant_id,
    )
    assert persisted_inbox is not None
    assert persisted_inbox.delivery_id == first.delivery.delivery_id
    assert persisted_inbox.result_checksum == result_checksum

    second_claim_at = case.now()
    second = case.store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=subscription_id,
            subscription_version=2,
            lease_owner=f"{case.scope}:worker:2",
            requested_at=second_claim_at,
            limit=1,
        )
    )[0]
    duplicate = case.store.settle_delivery(
        DeliverySettlement(
            lease=second.lease,
            target_state=DeliveryState.ACKED,
            settled_at=second_claim_at + timedelta(seconds=1),
            inbox_entry=InboxEntry(
                event_id=candidate.event_id,
                consumer_effect_id=effect_id,
                completed_at=second_claim_at + timedelta(seconds=1),
                delivery_id=second.delivery.delivery_id,
                result_checksum=result_checksum,
            ),
        )
    )
    assert duplicate.delivery.state is DeliveryState.ACKED
    assert not duplicate.inbox_recorded
    assert case.store.get_inbox_entry(
        InboxKey(candidate.event_id, effect_id),
        tenant_id=candidate.tenant_id,
    ) == persisted_inbox

    third_claim_at = case.now()
    third = case.store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=subscription_id,
            subscription_version=3,
            lease_owner=f"{case.scope}:worker:3",
            requested_at=third_claim_at,
            limit=1,
        )
    )[0]
    with pytest.raises(EventConsumerIdempotencyError):
        case.store.settle_delivery(
            DeliverySettlement(
                lease=third.lease,
                target_state=DeliveryState.ACKED,
                settled_at=third_claim_at + timedelta(seconds=1),
                inbox_entry=InboxEntry(
                    event_id=candidate.event_id,
                    consumer_effect_id=effect_id,
                    completed_at=third_claim_at + timedelta(seconds=1),
                    result_checksum="sha256:" + "2" * 64,
                ),
            )
        )
    assert case.store.get_delivery(
        third.delivery.delivery_id,
        tenant_id=candidate.tenant_id,
    ).state is DeliveryState.CLAIMED


def test_conformance_expired_leases_exhaust_budget_into_dlq_and_checkpoint(
    event_store_case: EventStoreCase,
) -> None:
    case = event_store_case
    subscription = case.store.register_subscription(
        DurableSubscription(
            subscription_id=f"{case.scope}:crash-recovery",
            subscription_version=1,
            consumer_id=f"{case.scope}:crash-consumer",
            retry_policy=RetryPolicy(max_attempts=2),
            tenant_id=_tenant_id(case.scope),
        )
    )
    event = case.store.append_event(_candidate(case.scope, index=1)).event
    first_requested_at = case.now()
    first = case.store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=subscription.subscription_id,
            subscription_version=subscription.subscription_version,
            lease_owner=f"{case.scope}:crashed-worker:1",
            requested_at=first_requested_at,
            lease_duration_seconds=5,
            limit=1,
        )
    )[0]
    assert first.delivery.attempt_count == 1

    case.advance_clock(
        first.lease.lease_expires_at + timedelta(milliseconds=100)
    )
    second = case.store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=subscription.subscription_id,
            subscription_version=subscription.subscription_version,
            lease_owner=f"{case.scope}:crashed-worker:2",
            requested_at=case.now(),
            lease_duration_seconds=5,
            limit=1,
        )
    )[0]
    assert second.delivery.attempt_count == 2

    case.advance_clock(
        second.lease.lease_expires_at + timedelta(milliseconds=100)
    )
    assert case.store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=subscription.subscription_id,
            subscription_version=subscription.subscription_version,
            lease_owner=f"{case.scope}:must-not-claim",
            requested_at=case.now(),
            lease_duration_seconds=5,
            limit=1,
        )
    ) == ()
    terminal = case.store.get_delivery(
        second.delivery.delivery_id,
        tenant_id=event.tenant_id,
    )
    assert terminal is not None
    assert terminal.state is DeliveryState.DEAD_LETTER
    assert terminal.attempt_count == 2
    dead_letters = case.store.list_dead_letters(
        DeadLetterQuery(
            subscription_id=subscription.subscription_id,
            subscription_version=subscription.subscription_version,
            tenant_id=event.tenant_id,
        )
    ).records
    assert len(dead_letters) == 1
    assert dead_letters[0].attempt_count == 2
    assert dead_letters[0].reason_class == "lease_expired"
    checkpoint = case.store.get_checkpoint(
        CheckpointKey(
            subscription_id=subscription.subscription_id,
            subscription_version=subscription.subscription_version,
            stream_id=event.stream_id,
            tenant_id=event.tenant_id,
        )
    )
    assert checkpoint is not None
    assert checkpoint.highest_contiguous_terminal_sequence == event.stream_sequence
    assert checkpoint.terminal_disposition is DeliveryState.DEAD_LETTER


def test_event_runtime_projects_before_first_write_with_cross_backend_content_parity(
    cross_backend_event_stores: CrossBackendEventStores,
    postgres_conformance_dsn: str,
) -> None:
    import psycopg

    case = cross_backend_event_stores
    subscription = DurableSubscription(
        subscription_id=f"{case.scope}:runtime-subscription",
        subscription_version=1,
        consumer_id=f"{case.scope}:runtime-consumer",
        event_filter=SubscriptionFilter(event_types=frozenset({RUNTIME_EVENT_TYPE})),
        tenant_id=_tenant_id(case.scope),
    )
    for store in (case.sqlite, case.postgres):
        store.register_subscription(subscription)

    request = _runtime_publish_request(
        case.scope,
        index=1,
        payload={"message": "accepted", "token": RAW_RUNTIME_SECRET},
    )
    catalog = _runtime_security_catalog()
    sqlite_event = EventRuntime(
        store=case.sqlite,
        schema_catalog=catalog,
    ).publish(request)
    postgres_event = EventRuntime(
        store=case.postgres,
        schema_catalog=catalog,
    ).publish(request)

    persisted = (
        case.sqlite.get_event(request.event_id, tenant_id=request.tenant_id),
        case.postgres.get_event(request.event_id, tenant_id=request.tenant_id),
    )
    assert persisted == (sqlite_event, postgres_event)
    for event in persisted:
        assert event is not None
        assert dict(event.payload or {}) == {
            "message": "accepted",
            "token": "[REDACTED]",
        }
        assert RAW_RUNTIME_SECRET.encode() not in canonical_json_bytes(event.to_dict())
        event.verify_integrity()

    assert canonical_json_bytes(sqlite_event.candidate.content_projection()) == (
        canonical_json_bytes(postgres_event.candidate.content_projection())
    )
    assert sqlite_event.content_checksum == postgres_event.content_checksum
    assert sqlite_event.content_checksum == checksum_for(
        sqlite_event.candidate.content_projection()
    )
    for store in (case.sqlite, case.postgres):
        deliveries = store.list_deliveries(
            DeliveryQuery(
                subscription_id=subscription.subscription_id,
                subscription_version=1,
                tenant_id=subscription.tenant_id,
            )
        ).records
        assert [delivery.event_id for delivery in deliveries] == [request.event_id]

    with sqlite3.connect(case.sqlite.database) as connection:
        sqlite_raw = str(
            connection.execute(
                "SELECT event_json FROM durable_events WHERE event_id = ?",
                (request.event_id,),
            ).fetchone()[0]
        )
    with psycopg.connect(postgres_conformance_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT payload::text FROM durable_events WHERE event_id = %s",
                (request.event_id,),
            )
            postgres_raw = str(cursor.fetchone()[0])
    assert sqlite_raw.count(RAW_RUNTIME_SECRET) == 0
    assert postgres_raw.count(RAW_RUNTIME_SECRET) == 0


def test_event_runtime_schema_and_security_fail_before_any_durable_write(
    event_store_case: EventStoreCase,
) -> None:
    case = event_store_case
    subscription = case.store.register_subscription(
        DurableSubscription(
            subscription_id=f"{case.scope}:runtime-failure-subscription",
            subscription_version=1,
            consumer_id=f"{case.scope}:runtime-failure-consumer",
            event_filter=SubscriptionFilter(
                event_types=frozenset({RUNTIME_EVENT_TYPE})
            ),
            tenant_id=_tenant_id(case.scope),
        )
    )
    runtime = EventRuntime(
        store=case.store,
        schema_catalog=_runtime_security_catalog(),
    )
    schema_failure = _runtime_publish_request(
        case.scope,
        index=91,
        payload={"message": 42, "token": RAW_RUNTIME_SECRET},
    )
    security_failure = _runtime_publish_request(
        case.scope,
        index=92,
        payload={"message": "valid schema", "password": RAW_RUNTIME_SECRET},
    )

    with pytest.raises(EventSchemaValidationError):
        runtime.publish(schema_failure)
    with pytest.raises(EventSecurityError):
        runtime.publish(security_failure)

    for request in (schema_failure, security_failure):
        assert case.store.get_event(
            request.event_id,
            tenant_id=request.tenant_id,
        ) is None
    assert case.store.get_stream_high_watermark(
        schema_failure.stream_id,
        tenant_id=schema_failure.tenant_id,
    ) is None
    assert case.store.list_deliveries(
        DeliveryQuery(
            subscription_id=subscription.subscription_id,
            subscription_version=subscription.subscription_version,
            tenant_id=subscription.tenant_id,
        )
    ).records == ()


def test_sqlite_and_postgres_store_identical_candidate_content_and_checksum(
    tmp_path: Path,
    postgres_conformance_dsn: str,
) -> None:
    from infrastructure.storage.events.postgres import PostgresDurableEventStore

    scope = f"event-store-conformance:{uuid4().hex}"
    _cleanup_postgres_scope(postgres_conformance_dsn, scope)
    try:
        sqlite_store = SQLiteEventStore(
            tmp_path / "cross-backend.sqlite3",
            clock=lambda: SQLITE_OBSERVED_AT,
        )
        postgres_store = PostgresDurableEventStore(postgres_conformance_dsn)
        candidate = _candidate(scope, index=1)

        sqlite_event = sqlite_store.append_event(candidate).event
        postgres_event = postgres_store.append_event(candidate).event

        assert canonical_json_bytes(sqlite_event.candidate.to_dict()) == (
            canonical_json_bytes(postgres_event.candidate.to_dict())
        )
        assert sqlite_event.content_checksum == postgres_event.content_checksum
        assert sqlite_event.content_checksum == candidate.content_checksum
        assert sqlite_event.record_checksum == checksum_for(
            sqlite_event.record_projection()
        )
        assert postgres_event.record_checksum == checksum_for(
            postgres_event.record_projection()
        )

        sqlite_normalized = StoredEvent(
            sqlite_event.candidate,
            observed_at=NORMALIZED_OBSERVED_AT,
            stream_sequence=1,
        )
        postgres_normalized = StoredEvent(
            postgres_event.candidate,
            observed_at=NORMALIZED_OBSERVED_AT,
            stream_sequence=1,
        )
        assert sqlite_normalized.record_checksum == postgres_normalized.record_checksum
        assert canonical_json_bytes(sqlite_normalized.record_projection()) == (
            canonical_json_bytes(postgres_normalized.record_projection())
        )

        subscription = DurableSubscription(
            subscription_id=f"{scope}:projection",
            subscription_version=1,
            consumer_id=f"{scope}:consumer",
            tenant_id=_tenant_id(scope),
        )
        sqlite_store.register_subscription(subscription)
        postgres_store.register_subscription(subscription)
        second_candidate = _candidate(scope, index=2)
        sqlite_store.append_event(second_candidate)
        postgres_store.append_event(second_candidate)
        sqlite_delivery = sqlite_store.list_deliveries(
            DeliveryQuery(
                subscription_id=subscription.subscription_id,
                subscription_version=1,
                tenant_id=_tenant_id(scope),
            )
        ).records[-1]
        postgres_delivery = postgres_store.list_deliveries(
            DeliveryQuery(
                subscription_id=subscription.subscription_id,
                subscription_version=1,
                tenant_id=_tenant_id(scope),
            )
        ).records[-1]
        assert sqlite_delivery.delivery_id == postgres_delivery.delivery_id

        sqlite_claim = sqlite_store.claim_deliveries(
            DeliveryClaimRequest(
                subscription_id=subscription.subscription_id,
                subscription_version=1,
                lease_owner=f"{scope}:sqlite-worker",
                requested_at=SQLITE_OBSERVED_AT + timedelta(seconds=5),
                limit=1,
            )
        )[0]
        postgres_claim = postgres_store.claim_deliveries(
            DeliveryClaimRequest(
                subscription_id=subscription.subscription_id,
                subscription_version=1,
                lease_owner=f"{scope}:postgres-worker",
                requested_at=datetime.now(UTC),
                limit=1,
            )
        )[0]
        sqlite_dead = sqlite_store.settle_delivery(
            DeliverySettlement(
                lease=sqlite_claim.lease,
                target_state=DeliveryState.DEAD_LETTER,
                settled_at=SQLITE_OBSERVED_AT + timedelta(seconds=6),
                reason_class="permanent",
            )
        )
        postgres_dead = postgres_store.settle_delivery(
            DeliverySettlement(
                lease=postgres_claim.lease,
                target_state=DeliveryState.DEAD_LETTER,
                settled_at=datetime.now(UTC),
                reason_class="permanent",
            )
        )
        assert sqlite_dead.delivery.delivery_id == postgres_dead.delivery.delivery_id
        assert sqlite_dead.dead_letter_id == postgres_dead.dead_letter_id
    finally:
        _cleanup_postgres_scope(postgres_conformance_dsn, scope)


def test_conformance_authorized_redelivery_preserves_source_and_prior_ledgers(
    event_store_case: EventStoreCase,
) -> None:
    case = event_store_case
    subscription = case.store.register_subscription(
        DurableSubscription(
            subscription_id=f"{case.scope}:redelivery",
            subscription_version=1,
            consumer_id=f"{case.scope}:redelivery-consumer",
            supports_out_of_order_repair=True,
            tenant_id=_tenant_id(case.scope),
        )
    )
    originals = tuple(
        case.store.append_event(_candidate(case.scope, index=index)).event
        for index in (1, 2)
    )
    for index in (1, 2):
        requested_at = case.now()
        claim = case.store.claim_deliveries(
            DeliveryClaimRequest(
                subscription.subscription_id,
                subscription.subscription_version,
                f"{case.scope}:redelivery-worker:{index}",
                requested_at,
                limit=1,
            )
        )[0]
        case.store.settle_delivery(
            DeliverySettlement(
                claim.lease,
                DeliveryState.ACKED,
                requested_at + timedelta(seconds=index),
            )
        )

    request = RedeliveryRequest(
        redelivery_id=f"{case.scope}:redelivery-request",
        subscription=subscription.key,
        source_stream_id=_stream_id(case.scope),
        from_sequence=1,
        through_sequence=2,
        requested_at=case.now() + timedelta(seconds=10),
        operator_id=f"{case.scope}:operator",
        operator_reason="authorized deterministic repair",
        authorization_evidence_ref=f"{case.scope}:authz:redelivery",
        tenant_id=_tenant_id(case.scope),
    )

    first = case.store.begin_redelivery(request)
    duplicate = case.store.begin_redelivery(request)

    assert duplicate == first
    assert first.captured_high_watermark == 2
    assert [item.stream_sequence for item in first.items] == [1, 2]
    assert [item.delivery_generation for item in first.items] == [2, 2]
    assert case.store.get_redelivery_report(
        request.redelivery_id,
        tenant_id=request.tenant_id,
    ) == first
    assert case.store.get_redelivery_report(request.redelivery_id) is None
    deliveries = case.store.list_deliveries(
        DeliveryQuery(
            subscription_id=subscription.subscription_id,
            subscription_version=subscription.subscription_version,
            tenant_id=subscription.tenant_id,
            limit=10,
        )
    ).records
    assert sorted(delivery.delivery_generation for delivery in deliveries) == [1, 1, 2, 2]
    for original in originals:
        assert case.store.get_event(
            original.event_id,
            tenant_id=original.tenant_id,
        ) == original


def _candidate(
    scope: str,
    *,
    index: int,
    stream_id: str | None = None,
    tenant_id: str | None | object = ...,
    event_type: str = "io.newsroom.test.conformance",
) -> EventCandidate:
    actual_tenant = _tenant_id(scope) if tenant_id is ... else tenant_id
    return EventCandidate(
        event_id=_event_id(scope, index),
        event_type=event_type,
        data_schema="newsroom.test.event-store-conformance/v1",
        source="tests.infrastructure.storage.events.conformance",
        occurred_at=OCCURRED_AT + timedelta(microseconds=index),
        stream_id=stream_id or _stream_id(scope),
            business_context=BusinessContext(
                run_id=scope,
                graph_id="tests.event-store-conformance",
                graph_version="1",
                graph_ref="tests.event-store-conformance@1",
                graph_checksum="sha256:" + "a" * 64,
            ),
        producer=ProducerIdentity(component="event-store-conformance", version="1"),
        tenant_id=actual_tenant,
        security_classification=SecurityClassification.INTERNAL,
        payload={"index": index, "nested": {"safe": True}},
        extensions={"io.newsroom.conformance": "shared"},
    )


def _runtime_security_catalog() -> EventSchemaCatalog:
    catalog = EventSchemaCatalog()
    catalog.register(
        EventSchemaRegistration(
            event_type=RUNTIME_EVENT_TYPE,
            data_schema=RUNTIME_DATA_SCHEMA,
            json_schema={
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                    "token": {"type": "string"},
                    "password": {"type": "string"},
                },
                "required": ["message"],
                "additionalProperties": False,
            },
            sensitivity_policy=SensitivityPolicy(
                field_rules={"/token": "sensitive"},
                redact_sensitive=True,
            ),
            current=True,
        )
    )
    return catalog


def _runtime_publish_request(
    scope: str,
    *,
    index: int,
    payload: dict[str, object],
) -> EventPublishRequest:
    return EventPublishRequest(
        event_id=f"{scope}:runtime-event:{index}",
        event_type=RUNTIME_EVENT_TYPE,
        data_schema=RUNTIME_DATA_SCHEMA,
        source="tests.infrastructure.storage.events.runtime-conformance",
        occurred_at=OCCURRED_AT + timedelta(microseconds=index),
        stream_id=f"{scope}:runtime-stream",
        business_context=BusinessContext(
            run_id=scope,
            graph_id="tests.event-store-conformance",
            graph_version="1",
            graph_ref="tests.event-store-conformance@1",
            graph_checksum="sha256:" + "a" * 64,
        ),
        producer=ProducerIdentity(component="event-runtime-conformance", version="1"),
        tenant_id=_tenant_id(scope),
        security_classification=SecurityClassification.INTERNAL,
        payload=payload,
        extensions={"io.newsroom.conformance": "runtime-security"},
    )


def _event_id(scope: str, index: int) -> str:
    return f"{scope}:event:{index}"


def _stream_id(scope: str) -> str:
    return f"{scope}:stream"


def _tenant_id(scope: str) -> str:
    return f"{scope}:tenant"


def _cleanup_postgres_scope(dsn: str, scope: str) -> None:
    import psycopg

    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            for table, column in (
                ("event_retirement_cancellation_items", "cancellation_id"),
                ("event_retirement_cancellation_reports", "cancellation_id"),
                ("event_redelivery_items", "redelivery_id"),
                ("event_redelivery_reports", "redelivery_id"),
                ("event_inbox", "event_id"),
                ("event_dead_letters", "event_id"),
                ("event_deliveries", "event_id"),
                ("event_consumer_checkpoints", "subscription_id"),
                ("event_subscription_stream_states", "subscription_id"),
                ("event_subscription_status_audit", "subscription_id"),
                ("event_subscriptions", "subscription_id"),
                ("event_replay_reports", "replay_id"),
                ("event_quarantine", "quarantine_id"),
                ("durable_events", "event_id"),
                ("event_stream_sequences", "stream_id"),
            ):
                cursor.execute(
                    f"DELETE FROM {table} WHERE {column} LIKE %s",  # noqa: S608
                    (f"{scope}:%",),
                )
        connection.commit()
