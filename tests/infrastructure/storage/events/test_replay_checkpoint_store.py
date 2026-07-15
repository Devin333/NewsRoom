from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import textwrap
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator
from uuid import uuid4

import pytest

from framework.events.canonical import BusinessContext, EventCandidate, ProducerIdentity
from framework.events.errors import (
    EventStoreUnavailableError,
    ReplayCheckpointCollisionError,
    ReplayCheckpointCorruptionError,
)
from framework.events.runtime.models import ReplayMode
from framework.events.runtime.replay_engine import (
    ReplayCheckpoint,
    ReplayCheckpointStorePort,
)
from infrastructure.storage.events.replay_checkpoints import (
    PostgresReplayCheckpointStore,
    SQLiteReplayCheckpointStore,
)
from infrastructure.storage.events.sqlite import SQLiteEventStore


@dataclass(frozen=True)
class ReplayCheckpointStoreCase:
    backend: str
    store: ReplayCheckpointStorePort
    scope: str


def test_postgres_checkpoint_optional_dependency_fails_with_typed_store_error() -> None:
    script = textwrap.dedent(
        """
        import builtins

        real_import = builtins.__import__

        def without_psycopg(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "psycopg" or name.startswith("psycopg."):
                raise ModuleNotFoundError(
                    "blocked optional psycopg dependency",
                    name="psycopg",
                )
            return real_import(name, globals, locals, fromlist, level)

        builtins.__import__ = without_psycopg

        from framework.events import EventStoreUnavailableError
        from infrastructure.storage.events import PostgresReplayCheckpointStore
        from infrastructure.storage.postgres.dsn import normalize_dsn

        assert normalize_dsn("jdbc:postgresql://example/test") == "postgresql://example/test"
        try:
            PostgresReplayCheckpointStore("postgresql://example/test")
        except EventStoreUnavailableError:
            pass
        else:
            raise AssertionError("missing psycopg did not fail with EventStoreUnavailableError")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[4],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr


def test_postgres_checkpoint_does_not_mask_unrelated_missing_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import builtins

    real_import = builtins.__import__

    def missing_driver_dependency(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "psycopg":
            raise ModuleNotFoundError(
                "missing unrelated driver dependency",
                name="driver_internal_dependency",
            )
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", missing_driver_dependency)

    with pytest.raises(ModuleNotFoundError) as error:
        PostgresReplayCheckpointStore("postgresql://example/test")

    assert error.value.name == "driver_internal_dependency"


@pytest.fixture(scope="session")
def replay_checkpoint_postgres_dsn() -> str:
    dsn = os.getenv("NEWS_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip(
            "PostgreSQL replay-checkpoint conformance requires NEWS_TEST_POSTGRES_DSN"
        )
    psycopg = pytest.importorskip("psycopg")
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


@pytest.fixture(params=("sqlite", "postgres"))
def replay_checkpoint_store_case(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> Iterator[ReplayCheckpointStoreCase]:
    scope = f"replay-checkpoint:{uuid4().hex}"
    if request.param == "sqlite":
        database = tmp_path / "events.sqlite3"
        _seed_sqlite_stream(database, scope, tenant_id=f"{scope}:tenant")
        _seed_sqlite_stream(database, scope, tenant_id=None)
        yield ReplayCheckpointStoreCase(
            backend="sqlite",
            store=SQLiteReplayCheckpointStore(database),
            scope=scope,
        )
        return

    dsn = request.getfixturevalue("replay_checkpoint_postgres_dsn")
    _seed_postgres_stream(dsn, scope, tenant_id=f"{scope}:tenant")
    _seed_postgres_stream(dsn, scope, tenant_id=None)
    try:
        yield ReplayCheckpointStoreCase(
            backend="postgres",
            store=PostgresReplayCheckpointStore(dsn),
            scope=scope,
        )
    finally:
        _cleanup_postgres(dsn, scope)


def test_checkpoint_store_conformance_round_trip_tenant_scope_and_exact_idempotence(
    replay_checkpoint_store_case: ReplayCheckpointStoreCase,
) -> None:
    case = replay_checkpoint_store_case
    checkpoint = _checkpoint(case.scope, last_sequence=1)

    assert callable(case.store.save_checkpoint)
    assert callable(case.store.get_checkpoint)
    assert case.store.save_checkpoint(checkpoint) == checkpoint
    assert case.store.save_checkpoint(checkpoint) == checkpoint
    assert (
        case.store.get_checkpoint(
            checkpoint.checkpoint_id,
            tenant_id=checkpoint.tenant_id,
        )
        == checkpoint
    )
    assert case.store.get_checkpoint(checkpoint.checkpoint_id) is None
    assert (
        case.store.get_checkpoint(
            checkpoint.checkpoint_id,
            tenant_id=f"{case.scope}:other-tenant",
        )
        is None
    )

    with pytest.raises(ReplayCheckpointCollisionError):
        case.store.save_checkpoint(replace(checkpoint, tenant_id=None))
    assert case.store.get_checkpoint(checkpoint.checkpoint_id) is None


def test_checkpoint_store_conformance_monotonic_progress_and_collision_semantics(
    replay_checkpoint_store_case: ReplayCheckpointStoreCase,
) -> None:
    case = replay_checkpoint_store_case
    first = _checkpoint(case.scope, last_sequence=1)
    case.store.save_checkpoint(first)
    advanced = replace(
        first,
        last_sequence=2,
        history_checksum="sha256:" + "2" * 64,
        state={"count": 2},
    )
    assert case.store.save_checkpoint(advanced) == advanced

    for collision in (
        replace(advanced, history_checksum="sha256:" + "9" * 64),
        first,
        replace(advanced, source_stream_id=f"{case.scope}:other-stream"),
        replace(advanced, source_high_watermark=3),
        replace(advanced, runtime_version="runtime-v2"),
        replace(advanced, schema_catalog_version="catalog-v2"),
        replace(advanced, reducer_version="reducer-v2"),
        replace(advanced, parent_checkpoint_id=f"{case.scope}:other-parent"),
    ):
        with pytest.raises(ReplayCheckpointCollisionError):
            case.store.save_checkpoint(collision)
    assert (
        case.store.get_checkpoint(
            first.checkpoint_id,
            tenant_id=first.tenant_id,
        )
        == advanced
    )


def test_sqlite_checkpoint_survives_restart_and_shares_event_database(
    tmp_path: Path,
) -> None:
    database = tmp_path / "events.sqlite3"
    scope = "sqlite-restart"
    _seed_sqlite_stream(database, scope, tenant_id=f"{scope}:tenant")
    checkpoint = _checkpoint(scope, last_sequence=1)
    SQLiteReplayCheckpointStore(database).save_checkpoint(checkpoint)

    restarted = SQLiteReplayCheckpointStore(database, initialize=False)
    assert (
        restarted.get_checkpoint(
            checkpoint.checkpoint_id,
            tenant_id=checkpoint.tenant_id,
        )
        == checkpoint
    )
    assert (
        SQLiteEventStore(database, initialize=False).get_stream_high_watermark(
            checkpoint.source_stream_id,
            tenant_id=checkpoint.tenant_id,
        )
        == 2
    )


def test_sqlite_checkpoint_detects_tampered_checksum_and_index_columns(
    tmp_path: Path,
) -> None:
    database = tmp_path / "events.sqlite3"
    scope = "sqlite-corruption"
    _seed_sqlite_stream(database, scope, tenant_id=f"{scope}:tenant")
    checkpoint = _checkpoint(scope, last_sequence=1)
    store = SQLiteReplayCheckpointStore(database)
    store.save_checkpoint(checkpoint)
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TRIGGER trg_event_replay_checkpoints_equal_sequence")
        connection.execute(
            "UPDATE event_replay_checkpoints SET checkpoint_json = "
            "json_set(checkpoint_json, '$.checkpoint_checksum', ?) "
            "WHERE checkpoint_id = ?",
            ("sha256:" + "0" * 64, checkpoint.checkpoint_id),
        )
        connection.commit()
    with pytest.raises(ReplayCheckpointCorruptionError):
        store.get_checkpoint(checkpoint.checkpoint_id, tenant_id=checkpoint.tenant_id)


def test_sqlite_checkpoint_lock_and_read_only_fail_before_mutation(
    tmp_path: Path,
) -> None:
    database = tmp_path / "events.sqlite3"
    scope = "sqlite-failures"
    _seed_sqlite_stream(database, scope, tenant_id=f"{scope}:tenant")
    checkpoint = _checkpoint(scope, last_sequence=1)
    store = SQLiteReplayCheckpointStore(database, busy_timeout_seconds=0.01)
    blocker = sqlite3.connect(database, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(EventStoreUnavailableError):
            store.save_checkpoint(checkpoint)
    finally:
        blocker.rollback()
        blocker.close()
    assert (
        store.get_checkpoint(checkpoint.checkpoint_id, tenant_id=checkpoint.tenant_id)
        is None
    )

    read_only = SQLiteReplayCheckpointStore(database, read_only=True)
    with pytest.raises(EventStoreUnavailableError):
        read_only.save_checkpoint(checkpoint)
    assert (
        store.get_checkpoint(checkpoint.checkpoint_id, tenant_id=checkpoint.tenant_id)
        is None
    )


def test_sqlite_corrupt_database_fails_closed_on_open(tmp_path: Path) -> None:
    database = tmp_path / "events.sqlite3"
    database.write_bytes(b"not a sqlite database\x00" * 16)

    with pytest.raises(ReplayCheckpointCorruptionError):
        SQLiteReplayCheckpointStore(database, read_only=True)


def test_sqlite_checkpoint_process_exit_after_commit_is_durable(tmp_path: Path) -> None:
    database = tmp_path / "events.sqlite3"
    scope = "sqlite-process-commit"
    _seed_sqlite_stream(database, scope, tenant_id=f"{scope}:tenant")
    script = textwrap.dedent(
        f"""
        import os
        from framework.events.runtime.models import ReplayMode
        from framework.events.runtime.replay_engine import ReplayCheckpoint
        from infrastructure.storage.events.replay_checkpoints import SQLiteReplayCheckpointStore

        checkpoint = ReplayCheckpoint(
            checkpoint_id={f"{scope}:checkpoint"!r},
            mode=ReplayMode.REBUILD_STATE,
            source_stream_id={f"{scope}:stream"!r},
            last_sequence=2,
            source_high_watermark=2,
            runtime_version="runtime-v1",
            schema_catalog_version="catalog-v1",
            history_checksum="sha256:" + "2" * 64,
            state={{"count": 2}},
            reducer_id="counter",
            reducer_version="reducer-v1",
            tenant_id={f"{scope}:tenant"!r},
        )
        SQLiteReplayCheckpointStore({str(database)!r}).save_checkpoint(checkpoint)
        os._exit(79)
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[4],
        check=False,
        timeout=30,
    )

    assert result.returncode == 79
    restarted = SQLiteReplayCheckpointStore(database, initialize=False)
    checkpoint = restarted.get_checkpoint(
        f"{scope}:checkpoint",
        tenant_id=f"{scope}:tenant",
    )
    assert checkpoint is not None
    assert checkpoint.last_sequence == 2


def _checkpoint(scope: str, *, last_sequence: int) -> ReplayCheckpoint:
    return ReplayCheckpoint(
        checkpoint_id=f"{scope}:checkpoint",
        mode=ReplayMode.REBUILD_STATE,
        source_stream_id=f"{scope}:stream",
        last_sequence=last_sequence,
        source_high_watermark=2,
        runtime_version="runtime-v1",
        schema_catalog_version="catalog-v1",
        history_checksum="sha256:" + str(last_sequence) * 64,
        state={"count": last_sequence},
        reducer_id="counter",
        reducer_version="reducer-v1",
        parent_checkpoint_id=f"{scope}:parent",
        tenant_id=f"{scope}:tenant",
    )


def _candidate(scope: str, index: int, tenant_id: str | None) -> EventCandidate:
    return EventCandidate(
        event_id=f"{scope}:{tenant_id or 'unscoped'}:event:{index}",
        event_type="io.newsroom.test.replay-checkpoint",
        data_schema="newsroom.test.replay-checkpoint/v1",
        source="tests.infrastructure.storage.events",
        occurred_at=datetime(2026, 7, 15, tzinfo=UTC),
        stream_id=f"{scope}:stream",
        business_context=BusinessContext(run_id=scope),
        producer=ProducerIdentity(component="replay-checkpoint-test"),
        tenant_id=tenant_id,
        payload={"index": index},
    )


def _seed_sqlite_stream(database: Path, scope: str, tenant_id: str | None) -> None:
    store = SQLiteEventStore(database)
    for index in (1, 2):
        store.append_event(_candidate(scope, index, tenant_id))


def _seed_postgres_stream(dsn: str, scope: str, tenant_id: str | None) -> None:
    from infrastructure.storage.events.postgres import PostgresDurableEventStore

    store = PostgresDurableEventStore(dsn)
    for index in (1, 2):
        store.append_event(_candidate(scope, index, tenant_id))


def _cleanup_postgres(dsn: str, scope: str) -> None:
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
