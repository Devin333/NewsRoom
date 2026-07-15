from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from framework.events.canonical import (
    BusinessContext,
    EventCandidate,
    ProducerIdentity,
)
from framework.events.errors import (
    EventIdentityCollisionError,
    EventStaleLeaseError,
    EventStoreCapacityError,
)
from framework.events.ports import EventStorePort
from framework.events.runtime.models import (
    DeadLetterAction,
    DeadLetterDisposition,
    DeadLetterQuery,
    DeliveryClaimRequest,
    DeliveryLimits,
    DeliveryQuery,
    DeliverySettlement,
    DeliveryState,
    DurableSubscription,
    QuarantineDisposition,
    QuarantineReason,
    QuarantineRecord,
    ReplayMode,
    ReplayReportQuery,
    ReplayStartRequest,
    ReplayStatus,
    RetryPolicy,
    StreamReadRequest,
    SubscriptionStart,
    SubscriptionStartPolicy,
    SubscriptionStatus,
)
from framework.events.schema import SecurityClassification
from infrastructure.storage.events.sqlite import SQLiteEventStore


NOW = datetime(2026, 7, 15, 1, 0, tzinfo=UTC)


def _candidate(
    number: int,
    *,
    stream_id: str = "run:one",
    tenant_id: str | None = "tenant-a",
    event_type: str = "workflow_started",
) -> EventCandidate:
    return EventCandidate(
        event_id=f"evt-{number}",
        event_type=event_type,
        data_schema="newsroom.workflow-event/v1",
        source="tests.sqlite",
        occurred_at=NOW + timedelta(seconds=number),
        stream_id=stream_id,
        business_context=BusinessContext(run_id="one"),
        producer=ProducerIdentity(component="sqlite-tests", version="1"),
        tenant_id=tenant_id,
        security_classification=SecurityClassification.INTERNAL,
        payload={"number": number},
    )


def _store(tmp_path: Path, **kwargs: object) -> SQLiteEventStore:
    return SQLiteEventStore(tmp_path / "events.sqlite3", clock=lambda: NOW, **kwargs)


class _MutableClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current

    def advance(self, *, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


def test_sqlite_store_is_file_backed_wal_and_implements_port(tmp_path: Path) -> None:
    store = _store(tmp_path)

    assert isinstance(store, EventStorePort)
    assert store.durability_policy == {
        "journal_mode": "WAL",
        "synchronous": "FULL",
        "busy_timeout_ms": 5000,
        "host_scope": "single-host",
    }
    with sqlite3.connect(store.database) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 0
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert {
        "durable_events",
        "event_stream_sequences",
        "event_subscriptions",
        "event_subscription_stream_states",
        "event_deliveries",
        "event_inbox",
        "event_consumer_checkpoints",
        "event_dead_letters",
        "event_quarantine",
        "event_replay_reports",
    } <= table_names

    with pytest.raises(ValueError, match="file-backed"):
        SQLiteEventStore(":memory:")


def test_append_is_atomic_idempotent_ordered_and_tenant_scoped(tmp_path: Path) -> None:
    store = _store(tmp_path)
    subscription = DurableSubscription(
        "projection",
        1,
        "projection-consumer",
        tenant_id="tenant-a",
    )
    store.register_subscription(subscription)

    first = store.append_event(_candidate(1))
    duplicate = store.append_event(_candidate(1))
    second = store.append_event(_candidate(2))
    other_tenant = store.append_event(_candidate(3, tenant_id="tenant-b"))

    assert (first.event.stream_sequence, second.event.stream_sequence) == (1, 2)
    assert other_tenant.event.stream_sequence == 1
    assert first.created and first.pending_delivery_count == 1
    assert not duplicate.created and duplicate.pending_delivery_count == 0
    assert store.get_event("evt-1", tenant_id="tenant-b") is None
    assert [
        event.event_id
        for event in store.read_stream(
            StreamReadRequest("run:one", tenant_id="tenant-a")
        ).events
    ] == ["evt-1", "evt-2"]

    with pytest.raises(EventIdentityCollisionError):
        store.append_event(_candidate(1, event_type="workflow_failed"))


def test_unit_of_work_rolls_back_sequence_event_and_outbox(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.register_subscription(
        DurableSubscription("projection", 1, "consumer", tenant_id="tenant-a")
    )

    with store.unit_of_work() as transaction:
        transaction.append_event(_candidate(1))

    assert store.get_event("evt-1", tenant_id="tenant-a") is None
    assert store.get_stream_high_watermark("run:one", tenant_id="tenant-a") is None
    assert store.list_deliveries(DeliveryQuery(tenant_id="tenant-a")).records == ()

    committed = store.append_event(_candidate(2))
    assert committed.event.stream_sequence == 1


def test_stream_pagination_fixes_snapshot_and_filters(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.append_event(_candidate(1))
    store.append_event(_candidate(2, event_type="workflow_failed"))
    store.append_event(_candidate(3))

    first = store.read_stream(
        StreamReadRequest(
            "run:one",
            tenant_id="tenant-a",
            event_types=frozenset({"workflow_started"}),
            limit=1,
        )
    )
    assert [event.event_id for event in first.events] == ["evt-1"]
    assert first.high_watermark == 3
    assert first.next_cursor is not None

    store.append_event(_candidate(4))
    second = store.read_stream(
        StreamReadRequest(
            "run:one",
            tenant_id="tenant-a",
            event_types=frozenset({"workflow_started"}),
            cursor=first.next_cursor,
            limit=10,
        )
    )
    assert [event.event_id for event in second.events] == ["evt-3"]
    assert second.high_watermark == 3


@pytest.mark.parametrize(
    ("start", "expected"),
    [
        (SubscriptionStart(SubscriptionStartPolicy.EARLIEST), ["evt-1", "evt-2"]),
        (SubscriptionStart(SubscriptionStartPolicy.LATEST), []),
        (
            SubscriptionStart(SubscriptionStartPolicy.AT_SEQUENCE, start_sequence=2),
            ["evt-2"],
        ),
    ],
)
def test_subscription_registration_materializes_exact_start_boundary(
    tmp_path: Path,
    start: SubscriptionStart,
    expected: list[str],
) -> None:
    store = _store(tmp_path)
    store.append_event(_candidate(1))
    store.append_event(_candidate(2))

    store.register_subscription(
        DurableSubscription(
            "projection",
            1,
            "consumer",
            start=start,
            tenant_id="tenant-a",
        )
    )

    assert [
        delivery.event_id
        for delivery in store.list_deliveries(
            DeliveryQuery(tenant_id="tenant-a")
        ).records
    ] == expected


def test_registration_backfill_capacity_failure_rolls_back_all_streams(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    for number, stream_id in enumerate(
        ("run:one", "run:one", "run:two", "run:two"),
        1,
    ):
        store.append_event(_candidate(number, stream_id=stream_id))
    subscription = DurableSubscription(
        "bounded-backfill",
        1,
        "consumer",
        limits=DeliveryLimits(
            batch_size=1,
            max_in_flight=1,
            max_concurrency=1,
            pending_warning_threshold=2,
            pending_hard_limit=3,
        ),
        tenant_id="tenant-a",
    )

    with pytest.raises(EventStoreCapacityError, match="backfill"):
        store.register_subscription(subscription)

    assert store.get_subscription(subscription.key) is None
    assert store.list_deliveries(
        DeliveryQuery(
            subscription_id=subscription.subscription_id,
            subscription_version=subscription.subscription_version,
            tenant_id=subscription.tenant_id,
        )
    ).records == ()
    for stream_id in ("run:one", "run:two"):
        assert store.get_subscription_stream_state(
            subscription.key,
            stream_id,
            tenant_id=subscription.tenant_id,
        ) is None


def test_initial_retired_registration_is_rejected_without_side_effects(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    store.append_event(_candidate(1))
    subscription = DurableSubscription(
        "initially-retired",
        1,
        "consumer",
        status=SubscriptionStatus.RETIRED,
        tenant_id="tenant-a",
    )

    with pytest.raises(ValueError, match="initially RETIRED"):
        store.register_subscription(subscription)

    assert store.get_subscription(subscription.key) is None
    assert store.get_subscription_stream_state(
        subscription.key,
        "run:one",
        tenant_id="tenant-a",
    ) is None
    assert store.list_deliveries(
        DeliveryQuery(
            subscription_id=subscription.subscription_id,
            tenant_id="tenant-a",
        )
    ).records == ()


def test_duplicate_registration_ignores_dynamic_status_and_timestamps(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    definition = DurableSubscription("projection", 1, "consumer", tenant_id="tenant-a")
    registered = store.register_subscription(definition)
    paused = store.set_subscription_status(
        registered.key,
        SubscriptionStatus.PAUSED,
        changed_at=NOW + timedelta(seconds=1),
        reason="maintenance",
    )

    duplicate = store.register_subscription(
        replace(
            definition,
            created_at=NOW + timedelta(days=1),
            updated_at=NOW + timedelta(days=2),
        )
    )

    assert duplicate == paused
    assert duplicate.status is SubscriptionStatus.PAUSED


def test_paused_subscription_materializes_but_does_not_claim_and_retired_drains(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    subscription = store.register_subscription(
        DurableSubscription("projection", 1, "consumer", tenant_id="tenant-a")
    )
    store.set_subscription_status(
        subscription.key,
        SubscriptionStatus.PAUSED,
        changed_at=NOW,
        reason="maintenance",
    )
    store.append_event(_candidate(1))
    request = DeliveryClaimRequest("projection", 1, "worker", NOW)
    assert store.claim_deliveries(request) == ()

    store.set_subscription_status(
        subscription.key,
        SubscriptionStatus.RETIRED,
        changed_at=NOW + timedelta(seconds=1),
        reason="replace consumer",
    )
    claims = store.claim_deliveries(
        replace(request, requested_at=NOW + timedelta(seconds=2))
    )
    assert len(claims) == 1
    store.append_event(_candidate(2))
    deliveries = store.list_deliveries(DeliveryQuery(tenant_id="tenant-a")).records
    assert [delivery.event_id for delivery in deliveries] == ["evt-1"]

    with pytest.raises(ValueError, match="cannot be reactivated"):
        store.set_subscription_status(
            subscription.key,
            SubscriptionStatus.ACTIVE,
            changed_at=NOW + timedelta(seconds=3),
            reason="unsafe",
        )


def test_claim_fencing_retry_exhaustion_checkpoint_and_late_repair(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.register_subscription(
        DurableSubscription(
            "projection",
            1,
            "consumer",
            retry_policy=RetryPolicy(max_attempts=1),
            supports_out_of_order_repair=True,
            tenant_id="tenant-a",
        )
    )
    store.append_event(_candidate(1))
    store.append_event(_candidate(2))
    first_claim = store.claim_deliveries(
        DeliveryClaimRequest("projection", 1, "worker-a", NOW)
    )
    assert len(first_claim) == 1
    assert first_claim[0].event.event_id == "evt-1"

    with pytest.raises(EventStaleLeaseError):
        store.renew_delivery_lease(
            replace(first_claim[0].lease, lease_owner="stale-worker"),
            renewed_at=NOW + timedelta(seconds=1),
            lease_duration_seconds=30,
        )

    settlement = store.settle_delivery(
        DeliverySettlement(
            first_claim[0].lease,
            DeliveryState.RETRY_WAIT,
            NOW + timedelta(seconds=1),
            reason_class="poison",
            retry_available_at=NOW + timedelta(seconds=2),
        )
    )
    assert settlement.delivery.state is DeliveryState.DEAD_LETTER
    assert settlement.dead_letter_id is not None
    assert settlement.checkpoint is not None
    assert settlement.checkpoint.highest_contiguous_terminal_sequence == 1

    next_claim = store.claim_deliveries(
        DeliveryClaimRequest(
            "projection",
            1,
            "worker-b",
            NOW + timedelta(seconds=2),
        )
    )
    assert [claim.event.event_id for claim in next_claim] == ["evt-2"]
    repaired = store.requeue_dead_letter(
        DeadLetterAction(
            settlement.dead_letter_id,
            "operator",
            "repair poison input",
            NOW + timedelta(seconds=3),
            idempotency_ready=True,
        )
    )
    assert repaired.delivery_generation == 2
    assert repaired.state is DeliveryState.PENDING
    assert store.list_dead_letters(
        DeadLetterQuery(tenant_id="tenant-a")
    ).records[0].disposition is DeadLetterDisposition.REQUEUED


def test_requeue_capacity_failure_keeps_dead_letter_open(tmp_path: Path) -> None:
    store = _store(tmp_path)
    subscription = store.register_subscription(
        DurableSubscription(
            "bounded-repair",
            1,
            "consumer",
            retry_policy=RetryPolicy(max_attempts=1),
            limits=DeliveryLimits(
                batch_size=1,
                max_in_flight=1,
                max_concurrency=1,
                pending_warning_threshold=1,
                pending_hard_limit=2,
            ),
            supports_out_of_order_repair=True,
            tenant_id="tenant-a",
        )
    )
    store.append_event(_candidate(1, stream_id="run:dead"))
    claim = store.claim_deliveries(
        DeliveryClaimRequest("bounded-repair", 1, "worker", NOW, limit=1)
    )[0]
    dead = store.settle_delivery(
        DeliverySettlement(
            claim.lease,
            DeliveryState.DEAD_LETTER,
            NOW + timedelta(seconds=1),
            reason_class="poison",
        )
    )
    assert dead.dead_letter_id is not None
    store.append_event(_candidate(2, stream_id="run:two"))
    store.append_event(_candidate(3, stream_id="run:three"))

    with pytest.raises(EventStoreCapacityError, match="hard limit"):
        store.requeue_dead_letter(
            DeadLetterAction(
                dead.dead_letter_id,
                "operator",
                "repair poison input",
                NOW + timedelta(seconds=2),
                idempotency_ready=True,
            )
        )

    dead_letter = store.list_dead_letters(
        DeadLetterQuery(
            subscription_id=subscription.subscription_id,
            subscription_version=subscription.subscription_version,
            tenant_id=subscription.tenant_id,
        )
    ).records[0]
    assert dead_letter.disposition is DeadLetterDisposition.OPEN
    deliveries = store.list_deliveries(
        DeliveryQuery(
            subscription_id=subscription.subscription_id,
            subscription_version=subscription.subscription_version,
            tenant_id=subscription.tenant_id,
        )
    ).records
    assert len(deliveries) == 3
    assert max(delivery.delivery_generation for delivery in deliveries) == 1
    assert store.pending_delivery_stats(subscription.key).pending_count == 2


def test_max_concurrency_is_a_durable_lease_owner_slot(tmp_path: Path) -> None:
    clock = _MutableClock(NOW)
    store = SQLiteEventStore(tmp_path / "events.sqlite3", clock=clock)
    store.register_subscription(
        DurableSubscription(
            "concurrency",
            1,
            "consumer",
            limits=DeliveryLimits(
                batch_size=1,
                max_in_flight=3,
                max_concurrency=1,
                pending_warning_threshold=3,
                pending_hard_limit=6,
            ),
            tenant_id="tenant-a",
        )
    )
    for number in range(1, 4):
        store.append_event(_candidate(number, stream_id=f"run:{number}"))

    first = store.claim_deliveries(
        DeliveryClaimRequest(
            "concurrency",
            1,
            "worker-a",
            NOW - timedelta(days=1),
            lease_duration_seconds=5,
            limit=1,
        )
    )
    assert len(first) == 1
    assert first[0].lease.lease_expires_at == NOW + timedelta(seconds=5)
    assert store.claim_deliveries(
        DeliveryClaimRequest("concurrency", 1, "worker-b", NOW, limit=1)
    ) == ()
    assert len(
        store.claim_deliveries(
            DeliveryClaimRequest(
                "concurrency",
                1,
                "worker-a",
                NOW,
                lease_duration_seconds=5,
                limit=1,
            )
        )
    ) == 1

    clock.advance(seconds=6)
    replacement = store.claim_deliveries(
        DeliveryClaimRequest(
            "concurrency",
            1,
            "worker-b",
            NOW - timedelta(days=1),
            lease_duration_seconds=5,
            limit=1,
        )
    )
    assert len(replacement) == 1
    assert replacement[0].lease.lease_owner == "worker-b"
    assert replacement[0].lease.lease_expires_at == clock.current + timedelta(seconds=5)


def test_store_clock_fences_backdated_renew_and_settlement(tmp_path: Path) -> None:
    clock = _MutableClock(NOW)
    store = SQLiteEventStore(tmp_path / "events.sqlite3", clock=clock)
    store.register_subscription(
        DurableSubscription("lease-clock", 1, "consumer", tenant_id="tenant-a")
    )
    store.append_event(_candidate(1))
    first = store.claim_deliveries(
        DeliveryClaimRequest(
            "lease-clock",
            1,
            "worker-a",
            NOW - timedelta(days=1),
            lease_duration_seconds=5,
            limit=1,
        )
    )[0]
    assert first.lease.lease_expires_at == NOW + timedelta(seconds=5)

    clock.advance(seconds=4.9999)
    assert store.claim_deliveries(
        DeliveryClaimRequest(
            "lease-clock",
            1,
            "worker-too-early",
            NOW + timedelta(days=1),
            lease_duration_seconds=5,
            limit=1,
        )
    ) == ()
    clock.advance(seconds=0.0002)
    with pytest.raises(EventStaleLeaseError):
        store.renew_delivery_lease(
            first.lease,
            renewed_at=NOW - timedelta(days=1),
            lease_duration_seconds=5,
        )
    with pytest.raises(EventStaleLeaseError):
        store.settle_delivery(
            DeliverySettlement(
                first.lease,
                DeliveryState.ACKED,
                NOW - timedelta(days=1),
            )
        )

    recovered = store.claim_deliveries(
        DeliveryClaimRequest(
            "lease-clock",
            1,
            "worker-b",
            NOW - timedelta(days=1),
            lease_duration_seconds=5,
            limit=1,
        )
    )[0]
    renewed = store.renew_delivery_lease(
        recovered.lease,
        renewed_at=NOW - timedelta(days=1),
        lease_duration_seconds=10,
    )
    assert renewed.lease_expires_at == clock.current + timedelta(seconds=10)


def test_pending_delivery_stats_separate_lag_and_late_repair(tmp_path: Path) -> None:
    clock = _MutableClock(NOW)
    store = SQLiteEventStore(tmp_path / "events.sqlite3", clock=clock)
    subscription = store.register_subscription(
        DurableSubscription(
            "repair-stats",
            1,
            "consumer",
            retry_policy=RetryPolicy(max_attempts=1),
            limits=DeliveryLimits(
                batch_size=1,
                max_in_flight=1,
                max_concurrency=1,
                pending_warning_threshold=1,
                pending_hard_limit=3,
            ),
            supports_out_of_order_repair=True,
            tenant_id="tenant-a",
        )
    )
    store.append_event(_candidate(1))
    claim = store.claim_deliveries(
        DeliveryClaimRequest("repair-stats", 1, "worker", NOW, limit=1)
    )[0]
    dead = store.settle_delivery(
        DeliverySettlement(
            claim.lease,
            DeliveryState.DEAD_LETTER,
            NOW,
            reason_class="poison",
        )
    )
    assert dead.dead_letter_id is not None
    store.append_event(_candidate(2, stream_id="run:two"))
    clock.advance(seconds=7)
    store.requeue_dead_letter(
        DeadLetterAction(
            dead.dead_letter_id,
            "operator",
            "repair poison input",
            clock.current,
            idempotency_ready=True,
        )
    )

    stats = store.pending_delivery_stats(subscription.key)

    assert stats.pending_count == 2
    assert stats.lag == 1
    assert stats.late_repair_pending_count == 1
    assert stats.warning_threshold_reached
    assert stats.capacity_remaining == 1
    assert stats.oldest_pending_at == NOW
    assert stats.oldest_pending_age_seconds == 7


def test_pending_stats_order_mixed_rfc3339_precision_chronologically(
    tmp_path: Path,
) -> None:
    clock = _MutableClock(NOW)
    store = SQLiteEventStore(tmp_path / "events.sqlite3", clock=clock)
    subscription = store.register_subscription(
        DurableSubscription("mixed-time", 1, "consumer", tenant_id="tenant-a")
    )
    store.append_event(_candidate(1, stream_id="run:first"))
    clock.advance(seconds=0.1)
    store.append_event(_candidate(2, stream_id="run:second"))

    stats = store.pending_delivery_stats(subscription.key)

    assert stats.oldest_pending_at == NOW
    assert stats.oldest_pending_age_seconds == 0.1


def test_quarantine_replay_backup_and_restore_are_durable(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.append_event(_candidate(1))
    quarantine = QuarantineRecord(
        "quarantine-1",
        "legacy-jsonl",
        QuarantineReason.CORRUPT_RECORD,
        NOW,
        tenant_id="tenant-a",
        redacted_diagnostic="checksum mismatch",
    )
    store.save_quarantine(quarantine)
    resolved = store.resolve_quarantine(
        quarantine.quarantine_id,
        QuarantineDisposition.REJECTED,
        operator_id="operator",
        reason="cannot recover",
        resolved_at=NOW + timedelta(seconds=1),
    )
    assert resolved.disposition is QuarantineDisposition.REJECTED

    replay = store.begin_replay(
        ReplayStartRequest(
            "replay-1",
            ReplayMode.REBUILD_STATE,
            "run:one",
            NOW,
            tenant_id="tenant-a",
        )
    )
    store.append_event(_candidate(2))
    running = store.update_replay_report(
        replace(replay, status=ReplayStatus.RUNNING)
    )
    assert running.high_watermark == 1
    assert store.list_replay_reports(
        ReplayReportQuery(tenant_id="tenant-a")
    ).reports == (running,)

    backup = store.backup_to(tmp_path / "backup.sqlite3")
    restored = SQLiteEventStore.restore_backup(
        backup,
        tmp_path / "restored.sqlite3",
    )
    restored.verify_integrity(full=True)
    assert restored.get_event("evt-2", tenant_id="tenant-a") is not None
    assert (
        restored.get_replay_report("replay-1", tenant_id="tenant-a").high_watermark
        == 1
    )


def test_pending_hard_limit_fails_append_before_event_commit(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.register_subscription(
        DurableSubscription(
            "projection",
            1,
            "consumer",
            limits=DeliveryLimits(
                batch_size=1,
                max_in_flight=1,
                max_concurrency=1,
                pending_warning_threshold=1,
                pending_hard_limit=2,
            ),
            tenant_id="tenant-a",
        )
    )
    store.append_event(_candidate(1))
    store.append_event(_candidate(2))

    with pytest.raises(EventStoreCapacityError):
        store.append_event(_candidate(3))

    assert store.get_event("evt-3", tenant_id="tenant-a") is None
    assert store.get_stream_high_watermark("run:one", tenant_id="tenant-a") == 2
