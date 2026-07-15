from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

import pytest


pytestmark = pytest.mark.skipif(
    os.getenv("NEWSROOM_RUN_POSTGRES_EVENT_INTEGRATION") != "1",
    reason=(
        "real PostgreSQL event integration is an explicit gate; set "
        "NEWSROOM_RUN_POSTGRES_EVENT_INTEGRATION=1"
    ),
)


def test_real_postgres_same_run_concurrent_writers_allocate_unique_offsets() -> None:
    """Reproduce the former COUNT/INSERT race against real transactions."""

    dsn = os.getenv("NEWS_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.fail("NEWS_TEST_POSTGRES_DSN is required for the real PostgreSQL gate")

    import psycopg
    from psycopg.conninfo import conninfo_to_dict

    database_name = str(conninfo_to_dict(dsn).get("dbname") or "").casefold()
    if "test" not in database_name:
        pytest.fail("NEWS_TEST_POSTGRES_DSN must select a database containing 'test'")

    from infrastructure.storage.events import EventRecord
    from infrastructure.storage.postgres import PostgresEventStore

    run_id = f"durable-race-{uuid4().hex}"
    event_count = 32
    store = PostgresEventStore(dsn)

    def append(index: int) -> int:
        return store.append_event(
            EventRecord(
                event_id=f"{run_id}-event-{index}",
                run_id=run_id,
                event_type="durable_race_probe",
                timestamp=datetime.now(UTC),
                payload={"index": index},
            )
        )

    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            returned_offsets = list(executor.map(append, range(event_count)))

        with psycopg.connect(dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT event_offset
                    FROM workflow_events
                    WHERE run_id = %s
                    ORDER BY event_offset
                    """,
                    (run_id,),
                )
                committed_offsets = [int(row[0]) for row in cursor.fetchall()]

        expected_offsets = list(range(event_count))
        assert sorted(returned_offsets) == expected_offsets
        assert committed_offsets == expected_offsets
        assert len(set(committed_offsets)) == event_count
    finally:
        with psycopg.connect(dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM workflow_events WHERE run_id = %s",
                    (run_id,),
                )
            connection.commit()
