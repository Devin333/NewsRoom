from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest


pytestmark = pytest.mark.skipif(
    os.getenv("NEWSROOM_RUN_POSTGRES_EVENT_INTEGRATION") != "1",
    reason=(
        "real PostgreSQL replay-checkpoint integration is an explicit gate; set "
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

    if "test" not in str(conninfo_to_dict(dsn).get("dbname") or "").casefold():
        pytest.fail("NEWS_TEST_POSTGRES_DSN must select a database containing 'test'")
    migrations = (
        Path(__file__).resolve().parents[4]
        / "infrastructure"
        / "storage"
        / "postgres"
        / "migrations"
    )
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                (migrations / "006_durable_event_runtime.sql").read_text(
                    encoding="utf-8"
                )
            )
            cursor.execute(
                (migrations / "007_replay_checkpoints.sql").read_text(encoding="utf-8")
            )
        connection.commit()
    return dsn


@pytest.fixture
def scope(postgres_dsn: str) -> str:
    value = f"pg-replay-checkpoint:{uuid4().hex}"
    yield value
    _cleanup(postgres_dsn, value)


def test_real_postgres_concurrent_exact_retries_commit_one_checkpoint(
    postgres_dsn: str,
    scope: str,
) -> None:
    from framework.events.canonical import (
        BusinessContext,
        EventCandidate,
        ProducerIdentity,
    )
    from framework.events.runtime.models import ReplayMode
    from framework.events.runtime.replay_engine import ReplayCheckpoint
    from infrastructure.storage.events.postgres import PostgresDurableEventStore
    from infrastructure.storage.events.replay_checkpoints import (
        PostgresReplayCheckpointStore,
    )

    tenant_id = f"{scope}:tenant"
    stream_id = f"{scope}:stream"
    event_store = PostgresDurableEventStore(postgres_dsn)
    for index in (1, 2):
        event_store.append_event(
            EventCandidate(
                event_id=f"{scope}:event:{index}",
                event_type="io.newsroom.test.pg-replay-checkpoint",
                data_schema="newsroom.test.pg-replay-checkpoint/v1",
                source="tests.infrastructure.storage.events",
                occurred_at=datetime(2026, 7, 15, tzinfo=UTC),
                stream_id=stream_id,
                business_context=BusinessContext(run_id=scope),
                producer=ProducerIdentity(component="pg-replay-checkpoint-test"),
                tenant_id=tenant_id,
                payload={"index": index},
            )
        )
    checkpoint = ReplayCheckpoint(
        checkpoint_id=f"{scope}:checkpoint",
        mode=ReplayMode.REBUILD_STATE,
        source_stream_id=stream_id,
        last_sequence=2,
        source_high_watermark=2,
        last_event_id=f"{scope}:event:2",
        runtime_version="runtime-v1",
        schema_catalog_version="catalog-v1",
        history_checksum="sha256:" + "2" * 64,
        state={"count": 2},
        reducer_id="counter",
        reducer_version="reducer-v1",
        tenant_id=tenant_id,
    )
    store = PostgresReplayCheckpointStore(postgres_dsn)

    with ThreadPoolExecutor(max_workers=12) as executor:
        persisted = list(
            executor.map(lambda _index: store.save_checkpoint(checkpoint), range(32))
        )

    assert persisted == [checkpoint] * 32
    restarted = PostgresReplayCheckpointStore(postgres_dsn)
    assert (
        restarted.get_checkpoint(checkpoint.checkpoint_id, tenant_id=tenant_id)
        == checkpoint
    )
    assert restarted.get_checkpoint(checkpoint.checkpoint_id) is None

    import psycopg

    with psycopg.connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM event_replay_checkpoints "
                "WHERE tenant_scope = %s AND checkpoint_id = %s",
                (tenant_id, checkpoint.checkpoint_id),
            )
            assert int(cursor.fetchone()[0]) == 1


def _cleanup(dsn: str, scope: str) -> None:
    import psycopg

    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM event_replay_checkpoints WHERE checkpoint_id LIKE %s",
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
