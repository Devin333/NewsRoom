from __future__ import annotations

import sqlite3
import subprocess
import sys
import textwrap
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from framework.events.canonical import BusinessContext, EventCandidate, ProducerIdentity
from framework.events.errors import (
    EventStoreCapacityError,
    EventStoreCorruptionError,
    EventStoreUnavailableError,
)
from framework.events.runtime.models import (
    ConsumerEffectContract,
    DeliveryClaimRequest,
    DeliverySettlement,
    DeliveryState,
    DurableSubscription,
    EffectIdempotencyStrategy,
    InboxEntry,
)
from infrastructure.storage.events.sqlite import SQLiteEventStore


NOW = datetime(2026, 7, 15, 1, 0, tzinfo=UTC)


def _candidate(event_id: str = "evt-1") -> EventCandidate:
    return EventCandidate(
        event_id=event_id,
        event_type="workflow_started",
        data_schema="newsroom.workflow-event/v1",
        source="tests.sqlite.faults",
        occurred_at=NOW,
        stream_id="run:one",
        business_context=BusinessContext(run_id="one"),
        producer=ProducerIdentity(component="sqlite-fault-tests"),
        payload={"safe": True},
    )


def test_database_lock_timeout_is_typed_and_leaves_no_partial_append(
    tmp_path: Path,
) -> None:
    database = tmp_path / "events.sqlite3"
    store = SQLiteEventStore(database, busy_timeout_seconds=0.01, clock=lambda: NOW)
    blocker = sqlite3.connect(database, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(EventStoreUnavailableError):
            store.append_event(_candidate())
    finally:
        blocker.rollback()
        blocker.close()

    assert store.get_event("evt-1") is None


def test_query_only_connection_maps_write_to_unavailable(tmp_path: Path) -> None:
    database = tmp_path / "events.sqlite3"
    writable = SQLiteEventStore(database, clock=lambda: NOW)

    def query_only_connection() -> sqlite3.Connection:
        connection = sqlite3.connect(database, isolation_level=None)
        connection.execute("PRAGMA query_only=ON")
        return connection

    readonly = SQLiteEventStore(
        database,
        connection_factory=query_only_connection,
        initialize=False,
        clock=lambda: NOW,
    )
    with pytest.raises(EventStoreUnavailableError):
        readonly.append_event(_candidate())
    assert writable.get_event("evt-1") is None


def test_disk_full_error_maps_to_capacity_without_exposing_driver_message(
    tmp_path: Path,
) -> None:
    database = tmp_path / "events.sqlite3"
    SQLiteEventStore(database)

    def capacity_limited_connection() -> sqlite3.Connection:
        connection = sqlite3.connect(database, isolation_level=None)
        page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
        connection.execute(f"PRAGMA max_page_count={page_count}")
        return connection

    store = SQLiteEventStore(
        database,
        connection_factory=capacity_limited_connection,
        initialize=False,
    )
    with pytest.raises(EventStoreCapacityError, match="capacity"):
        store.append_event(
            replace(
                _candidate(),
                payload={"body": "x" * 60_000},
            )
        )

    assert SQLiteEventStore(database).get_event("evt-1") is None


def test_corrupt_database_fails_closed_on_open(tmp_path: Path) -> None:
    database = tmp_path / "events.sqlite3"
    database.write_bytes(b"not a sqlite database\x00" * 16)

    with pytest.raises(EventStoreCorruptionError):
        SQLiteEventStore(database, read_only=True)


def test_tampered_canonical_row_is_detected_before_read(tmp_path: Path) -> None:
    database = tmp_path / "events.sqlite3"
    store = SQLiteEventStore(database, clock=lambda: NOW)
    store.append_event(_candidate())
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute(
            "UPDATE durable_events SET event_type = 'tampered' WHERE event_id = 'evt-1'"
        )
        connection.commit()

    with pytest.raises(EventStoreCorruptionError, match="indexes disagree"):
        store.get_event("evt-1")


def test_single_host_multi_process_writers_allocate_contiguous_sequences(
    tmp_path: Path,
) -> None:
    from framework.events.runtime import StreamReadRequest

    database = tmp_path / "events.sqlite3"
    start_gate = tmp_path / "start-writers"
    store = SQLiteEventStore(database, busy_timeout_seconds=15, clock=lambda: NOW)
    worker_count = 4
    events_per_worker = 4
    script = textwrap.dedent(
        """
        import sys
        import time
        from datetime import UTC, datetime
        from pathlib import Path

        from framework.events.canonical import (
            BusinessContext,
            EventCandidate,
            ProducerIdentity,
        )
        from infrastructure.storage.events.sqlite import SQLiteEventStore

        database = Path(sys.argv[1])
        start_gate = Path(sys.argv[2])
        worker_id = int(sys.argv[3])
        events_per_worker = int(sys.argv[4])
        deadline = time.monotonic() + 15
        while not start_gate.exists():
            if time.monotonic() >= deadline:
                raise TimeoutError("multi-process SQLite start gate timed out")
            time.sleep(0.01)

        store = SQLiteEventStore(
            database,
            initialize=False,
            busy_timeout_seconds=15,
        )
        for event_index in range(events_per_worker):
            store.append_event(
                EventCandidate(
                    event_id=f"evt-process-{worker_id}-{event_index}",
                    event_type="workflow_started",
                    data_schema="newsroom.workflow-event/v1",
                    source="tests.sqlite.multi-process",
                    occurred_at=datetime(2026, 7, 15, 1, 0, tzinfo=UTC),
                    stream_id="run:multi-process",
                    business_context=BusinessContext(run_id="multi-process"),
                    producer=ProducerIdentity(component="sqlite-process-writer"),
                    payload={"worker": worker_id, "index": event_index},
                )
            )
        """
    )
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                script,
                str(database),
                str(start_gate),
                str(worker_id),
                str(events_per_worker),
            ],
            cwd=Path(__file__).resolve().parents[4],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for worker_id in range(worker_count)
    ]
    try:
        start_gate.touch()
        results = [process.communicate(timeout=30) for process in processes]
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)

    for process, (stdout, stderr) in zip(processes, results, strict=True):
        assert process.returncode == 0, f"stdout={stdout!r}; stderr={stderr!r}"

    expected_count = worker_count * events_per_worker
    store.verify_integrity(full=True)
    page = store.read_stream(
        StreamReadRequest(stream_id="run:multi-process", limit=expected_count)
    )
    assert [event.stream_sequence for event in page.events] == list(
        range(1, expected_count + 1)
    )
    assert {event.event_id for event in page.events} == {
        f"evt-process-{worker_id}-{event_index}"
        for worker_id in range(worker_count)
        for event_index in range(events_per_worker)
    }


def test_process_death_before_commit_recovers_without_partial_rows(
    tmp_path: Path,
) -> None:
    database = tmp_path / "events.sqlite3"
    store = SQLiteEventStore(database, clock=lambda: NOW)
    script = textwrap.dedent(
        f"""
        import os
        from datetime import UTC, datetime
        from framework.events.canonical import BusinessContext, EventCandidate, ProducerIdentity
        from infrastructure.storage.events.sqlite import SQLiteEventStore

        store = SQLiteEventStore({str(database)!r}, initialize=False)
        connection = store._open_connection()
        connection.execute("BEGIN IMMEDIATE")
        event = EventCandidate(
            event_id="evt-crash",
            event_type="workflow_started",
            data_schema="newsroom.workflow-event/v1",
            source="crash-test",
            occurred_at=datetime(2026, 7, 15, 1, 0, tzinfo=UTC),
            stream_id="run:one",
            business_context=BusinessContext(run_id="one"),
            producer=ProducerIdentity(component="crash-test"),
            payload={{"safe": True}},
        )
        store._append_event(connection, event)
        os._exit(73)
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[4],
        check=False,
        timeout=30,
    )

    assert result.returncode == 73
    store.verify_integrity(full=True)
    assert store.get_event("evt-crash") is None
    assert store.get_stream_high_watermark("run:one") is None


def test_process_death_after_commit_preserves_complete_event(tmp_path: Path) -> None:
    database = tmp_path / "events.sqlite3"
    store = SQLiteEventStore(database, clock=lambda: NOW)
    script = textwrap.dedent(
        f"""
        import os
        from datetime import UTC, datetime
        from framework.events.canonical import BusinessContext, EventCandidate, ProducerIdentity
        from infrastructure.storage.events.sqlite import SQLiteEventStore

        store = SQLiteEventStore({str(database)!r}, initialize=False)
        event = EventCandidate(
            event_id="evt-committed",
            event_type="workflow_started",
            data_schema="newsroom.workflow-event/v1",
            source="crash-test",
            occurred_at=datetime(2026, 7, 15, 1, 0, tzinfo=UTC),
            stream_id="run:one",
            business_context=BusinessContext(run_id="one"),
            producer=ProducerIdentity(component="crash-test"),
            payload={{"safe": True}},
        )
        store.append_event(event)
        os._exit(74)
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[4],
        check=False,
        timeout=30,
    )

    assert result.returncode == 74
    store.verify_integrity(full=True)
    assert store.get_event("evt-committed") is not None
    assert store.get_stream_high_watermark("run:one") == 1


def test_existing_inbox_without_delivery_reference_fails_closed(tmp_path: Path) -> None:
    database = tmp_path / "events.sqlite3"
    store = SQLiteEventStore(database, clock=lambda: NOW)
    effect_id = "email-send"
    store.register_subscription(
        DurableSubscription(
            "effect",
            1,
            "consumer",
            effect=ConsumerEffectContract(
                performs_external_effects=True,
                consumer_effect_id=effect_id,
                idempotency_strategy=EffectIdempotencyStrategy.INBOX_TRANSACTION,
            ),
        )
    )
    candidate = _candidate()
    store.append_event(candidate)
    claim = store.claim_deliveries(
        DeliveryClaimRequest("effect", 1, "worker", NOW, limit=1)
    )[0]
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO event_inbox ("
            "event_id, consumer_effect_id, tenant_scope, tenant_id, completed_at, "
            "delivery_id, result_checksum"
            ") VALUES (?, ?, '', NULL, ?, NULL, ?)",
            (
                candidate.event_id,
                effect_id,
                NOW.isoformat().replace("+00:00", "Z"),
                "sha256:" + "1" * 64,
            ),
        )
        connection.commit()

    with pytest.raises(EventStoreCorruptionError, match="completing delivery"):
        store.settle_delivery(
            DeliverySettlement(
                lease=claim.lease,
                target_state=DeliveryState.ACKED,
                settled_at=NOW + timedelta(seconds=1),
                inbox_entry=InboxEntry(
                    event_id=candidate.event_id,
                    consumer_effect_id=effect_id,
                    completed_at=NOW + timedelta(seconds=1),
                    result_checksum="sha256:" + "1" * 64,
                ),
            )
        )
    assert store.get_delivery(claim.delivery.delivery_id).state is DeliveryState.CLAIMED
