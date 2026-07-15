from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, NoReturn

from framework.events.errors import (
    EventContractError,
    EventIntegrityError,
    EventStoreCapacityError,
    EventStoreError,
    EventStoreUnavailableError,
    ReplayCheckpointCollisionError,
    ReplayCheckpointCorruptionError,
)
from framework.events.runtime.replay_engine import ReplayCheckpoint
from framework.shared.json import json_loads, stable_json_dumps


SQLiteConnectionFactory = Callable[[], sqlite3.Connection]
PostgresConnectionFactory = Callable[[], Any]

_SQLITE_SCHEMA = r"""
CREATE TABLE IF NOT EXISTS event_replay_checkpoints (
    checkpoint_id TEXT PRIMARY KEY,
    tenant_scope TEXT NOT NULL,
    tenant_id TEXT,
    mode TEXT NOT NULL,
    source_stream_id TEXT NOT NULL,
    last_sequence INTEGER NOT NULL,
    source_high_watermark INTEGER NOT NULL,
    runtime_version TEXT NOT NULL,
    schema_catalog_version TEXT NOT NULL,
    reducer_scope TEXT NOT NULL,
    reducer_id TEXT,
    reducer_version TEXT,
    parent_checkpoint_scope TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    history_checksum TEXT NOT NULL,
    checkpoint_checksum TEXT NOT NULL,
    checkpoint_json TEXT NOT NULL,
    UNIQUE (checkpoint_id, tenant_scope),
    FOREIGN KEY (tenant_scope, source_stream_id)
        REFERENCES event_stream_sequences (tenant_scope, stream_id)
        ON DELETE RESTRICT,
    CHECK (tenant_scope = COALESCE(tenant_id, '')),
    CHECK (reducer_scope = COALESCE(reducer_id, '')),
    CHECK (parent_checkpoint_scope = COALESCE(parent_checkpoint_id, '')),
    CHECK (tenant_id IS NULL OR trim(tenant_id) <> ''),
    CHECK (trim(checkpoint_id) <> '' AND trim(source_stream_id) <> ''),
    CHECK (trim(runtime_version) <> '' AND trim(schema_catalog_version) <> ''),
    CHECK (mode IN ('rebuild_state', 'verify_history')),
    CHECK (last_sequence >= 0 AND source_high_watermark >= last_sequence),
    CHECK (
        (mode = 'rebuild_state' AND reducer_id IS NOT NULL
            AND reducer_version IS NOT NULL AND trim(reducer_version) <> '')
        OR
        (mode = 'verify_history' AND reducer_id IS NULL AND reducer_version IS NULL)
    ),
    CHECK (parent_checkpoint_id IS NULL OR trim(parent_checkpoint_id) <> ''),
    CHECK (parent_checkpoint_id IS NULL OR parent_checkpoint_id <> checkpoint_id),
    CHECK (history_checksum GLOB 'sha256:[0-9a-f]*' AND length(history_checksum) = 71),
    CHECK (checkpoint_checksum GLOB 'sha256:[0-9a-f]*' AND length(checkpoint_checksum) = 71),
    CHECK (json_valid(checkpoint_json))
);

CREATE INDEX IF NOT EXISTS idx_event_replay_checkpoints_scope_stream
    ON event_replay_checkpoints (
        tenant_scope, source_stream_id, mode, last_sequence, checkpoint_id
    );

CREATE TRIGGER IF NOT EXISTS trg_event_replay_checkpoints_immutable_identity
BEFORE UPDATE ON event_replay_checkpoints
FOR EACH ROW
WHEN OLD.checkpoint_id <> NEW.checkpoint_id
    OR OLD.tenant_scope <> NEW.tenant_scope
    OR OLD.mode <> NEW.mode
    OR OLD.source_stream_id <> NEW.source_stream_id
    OR OLD.source_high_watermark <> NEW.source_high_watermark
    OR OLD.runtime_version <> NEW.runtime_version
    OR OLD.schema_catalog_version <> NEW.schema_catalog_version
    OR OLD.reducer_scope <> NEW.reducer_scope
    OR COALESCE(OLD.reducer_version, '') <> COALESCE(NEW.reducer_version, '')
    OR OLD.parent_checkpoint_scope <> NEW.parent_checkpoint_scope
BEGIN
    SELECT RAISE(ABORT, 'replay checkpoint immutable identity changed');
END;

CREATE TRIGGER IF NOT EXISTS trg_event_replay_checkpoints_monotonic
BEFORE UPDATE ON event_replay_checkpoints
FOR EACH ROW
WHEN NEW.last_sequence < OLD.last_sequence
BEGIN
    SELECT RAISE(ABORT, 'replay checkpoint sequence regressed');
END;

CREATE TRIGGER IF NOT EXISTS trg_event_replay_checkpoints_equal_sequence
BEFORE UPDATE ON event_replay_checkpoints
FOR EACH ROW
WHEN NEW.last_sequence = OLD.last_sequence
    AND (
        NEW.history_checksum <> OLD.history_checksum
        OR NEW.checkpoint_checksum <> OLD.checkpoint_checksum
        OR NEW.checkpoint_json <> OLD.checkpoint_json
    )
BEGIN
    SELECT RAISE(ABORT, 'equal replay checkpoint sequence is not exactly idempotent');
END;
"""


class SQLiteReplayCheckpointStore:
    """Durable replay checkpoint slots in the canonical SQLite event DB."""

    def __init__(
        self,
        database: str | Path,
        *,
        busy_timeout_seconds: float = 5.0,
        synchronous: str = "FULL",
        read_only: bool = False,
        connection_factory: SQLiteConnectionFactory | None = None,
        initialize: bool = True,
    ) -> None:
        timeout = float(busy_timeout_seconds)
        if timeout < 0:
            raise ValueError("busy_timeout_seconds must be non-negative")
        policy = str(synchronous).strip().upper()
        if policy not in {"OFF", "NORMAL", "FULL", "EXTRA"}:
            raise ValueError("synchronous must be one of OFF, NORMAL, FULL, or EXTRA")
        self.database = str(database)
        self.busy_timeout_seconds = timeout
        self.synchronous = policy
        self.read_only = bool(read_only)
        self._connection_factory = connection_factory
        self._uri = self.database.startswith("file:")
        if self.database == ":memory:" and connection_factory is None:
            raise ValueError(
                "durable replay checkpoints require a file-backed database"
            )
        if connection_factory is None and not self._uri:
            path = Path(self.database)
            if not self.read_only:
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    raise EventStoreUnavailableError(
                        "create SQLite replay-checkpoint directory failed"
                    ) from exc
        if initialize:
            if self.read_only:
                self._verify_existing_schema()
            else:
                self._initialize_schema()

    def save_checkpoint(self, checkpoint: ReplayCheckpoint) -> ReplayCheckpoint:
        checkpoint = _validated_checkpoint(checkpoint)
        tenant_scope = _tenant_scope(checkpoint.tenant_id)
        with self._write() as connection:
            row = connection.execute(
                "SELECT * FROM event_replay_checkpoints WHERE checkpoint_id = ?",
                (checkpoint.checkpoint_id,),
            ).fetchone()
            if row is not None:
                existing = _checkpoint_from_sqlite_row(row)
                _validate_checkpoint_replacement(existing, checkpoint)
                if existing == checkpoint:
                    return existing
                connection.execute(
                    "UPDATE event_replay_checkpoints SET last_sequence = ?, "
                    "history_checksum = ?, checkpoint_checksum = ?, checkpoint_json = ? "
                    "WHERE checkpoint_id = ? AND tenant_scope = ?",
                    (
                        checkpoint.last_sequence,
                        checkpoint.history_checksum,
                        checkpoint.checkpoint_checksum,
                        _checkpoint_json(checkpoint),
                        checkpoint.checkpoint_id,
                        tenant_scope,
                    ),
                )
            else:
                connection.execute(
                    "INSERT INTO event_replay_checkpoints ("
                    "checkpoint_id, tenant_scope, tenant_id, mode, source_stream_id, "
                    "last_sequence, source_high_watermark, runtime_version, "
                    "schema_catalog_version, reducer_scope, reducer_id, reducer_version, "
                    "parent_checkpoint_scope, parent_checkpoint_id, history_checksum, "
                    "checkpoint_checksum, checkpoint_json"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    _sqlite_checkpoint_params(checkpoint),
                )
            persisted = connection.execute(
                "SELECT * FROM event_replay_checkpoints WHERE checkpoint_id = ? "
                "AND tenant_scope = ?",
                (checkpoint.checkpoint_id, tenant_scope),
            ).fetchone()
            if persisted is None:
                raise ReplayCheckpointCorruptionError(
                    "SQLite replay checkpoint write returned no durable row"
                )
            result = _checkpoint_from_sqlite_row(persisted)
            if result != checkpoint:
                raise ReplayCheckpointCorruptionError(
                    "SQLite replay checkpoint differs after durable write"
                )
            return result

    def get_checkpoint(
        self,
        checkpoint_id: str,
        *,
        tenant_id: str | None = None,
    ) -> ReplayCheckpoint | None:
        normalized_id = _required_text(checkpoint_id, "checkpoint_id")
        with self._read() as connection:
            row = connection.execute(
                "SELECT * FROM event_replay_checkpoints "
                "WHERE checkpoint_id = ? AND tenant_scope = ?",
                (normalized_id, _tenant_scope(tenant_id)),
            ).fetchone()
        return None if row is None else _checkpoint_from_sqlite_row(row)

    def _initialize_schema(self) -> None:
        with self._connection() as connection:
            try:
                journal_mode = str(
                    connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
                )
                if self.database != ":memory:" and journal_mode.casefold() != "wal":
                    raise EventStoreUnavailableError(
                        f"SQLite durable replay checkpoints require WAL mode; got {journal_mode}"
                    )
                connection.executescript(_SQLITE_SCHEMA)
                connection.commit()
            except sqlite3.Error as exc:
                raise _map_sqlite_error(
                    exc, operation="initialize SQLite replay checkpoint store"
                ) from exc

    def _verify_existing_schema(self) -> None:
        with self._read() as connection:
            try:
                row = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                    "AND name = 'event_replay_checkpoints'"
                ).fetchone()
            except sqlite3.Error as exc:
                raise _map_sqlite_error(
                    exc, operation="open read-only SQLite replay checkpoint store"
                ) from exc
        if row is None:
            raise ReplayCheckpointCorruptionError(
                "SQLite replay checkpoint schema is missing"
            )

    def _open_connection(self) -> sqlite3.Connection:
        try:
            if self._connection_factory is not None:
                connection = self._connection_factory()
            else:
                database = self.database
                uri = self._uri
                if self.read_only and not uri:
                    database = f"{Path(database).resolve().as_uri()}?mode=ro"
                    uri = True
                connection = sqlite3.connect(
                    database,
                    timeout=self.busy_timeout_seconds,
                    isolation_level=None,
                    uri=uri,
                    check_same_thread=False,
                )
            connection.row_factory = sqlite3.Row
            connection.execute(
                f"PRAGMA busy_timeout={int(self.busy_timeout_seconds * 1000)}"
            )
            connection.execute("PRAGMA foreign_keys=ON")
            if self.read_only:
                connection.execute("PRAGMA query_only=ON")
            else:
                connection.execute(f"PRAGMA synchronous={self.synchronous}")
            return connection
        except sqlite3.Error as exc:
            raise _map_sqlite_error(
                exc, operation="open SQLite replay checkpoint store"
            ) from exc

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._open_connection()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        try:
            with self._connection() as connection:
                yield connection
        except (EventStoreError, EventContractError, ValueError):
            raise
        except sqlite3.Error as exc:
            raise _map_sqlite_error(
                exc, operation="read SQLite replay checkpoint store"
            ) from exc

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        connection = self._open_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except (ReplayCheckpointCollisionError, ReplayCheckpointCorruptionError):
            connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise _map_sqlite_error(
                exc, operation="write SQLite replay checkpoint store"
            ) from exc
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()


class PostgresReplayCheckpointStore:
    """Durable replay checkpoint slots backed by PostgreSQL migration 007."""

    def __init__(
        self,
        dsn: str,
        *,
        connection_factory: PostgresConnectionFactory | None = None,
    ) -> None:
        if not isinstance(dsn, str) or not dsn.strip():
            raise ValueError("dsn is required")
        try:
            from infrastructure.storage.postgres.dsn import normalize_dsn

            if connection_factory is None:
                import psycopg
        except ModuleNotFoundError as exc:  # pragma: no cover - optional boundary
            if not _is_missing_psycopg(exc):
                raise
            raise EventStoreUnavailableError(
                "PostgreSQL replay checkpoint adapter requires psycopg"
            ) from exc

        self.dsn = normalize_dsn(dsn.strip())
        if connection_factory is None:

            def connect() -> Any:
                return psycopg.connect(self.dsn)

            connection_factory = connect
        self._connection_factory = connection_factory

    def save_checkpoint(self, checkpoint: ReplayCheckpoint) -> ReplayCheckpoint:
        checkpoint = _validated_checkpoint(checkpoint)
        tenant_scope = _tenant_scope(checkpoint.tenant_id)
        with self._transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"event-replay-checkpoint:{checkpoint.checkpoint_id}",),
                )
                cursor.execute(
                    "SELECT " + _POSTGRES_CHECKPOINT_COLUMNS + " "
                    "FROM event_replay_checkpoints WHERE checkpoint_id = %s FOR UPDATE",
                    (checkpoint.checkpoint_id,),
                )
                row = cursor.fetchone()
                if row is not None:
                    existing = _checkpoint_from_postgres_row(row)
                    _validate_checkpoint_replacement(existing, checkpoint)
                    if existing == checkpoint:
                        return existing
                    cursor.execute(
                        "UPDATE event_replay_checkpoints SET last_sequence = %s, "
                        "history_checksum = %s, checkpoint_checksum = %s, "
                        "checkpoint_json = %s::jsonb WHERE checkpoint_id = %s "
                        "AND tenant_scope = %s RETURNING "
                        + _POSTGRES_CHECKPOINT_COLUMNS,
                        (
                            checkpoint.last_sequence,
                            checkpoint.history_checksum,
                            checkpoint.checkpoint_checksum,
                            _checkpoint_json(checkpoint),
                            checkpoint.checkpoint_id,
                            tenant_scope,
                        ),
                    )
                else:
                    cursor.execute(
                        "INSERT INTO event_replay_checkpoints ("
                        "checkpoint_id, tenant_id, mode, source_stream_id, "
                        "last_sequence, source_high_watermark, runtime_version, "
                        "schema_catalog_version, reducer_id, reducer_version, "
                        "parent_checkpoint_id, history_checksum, checkpoint_checksum, "
                        "checkpoint_json) VALUES ("
                        "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb"
                        ") RETURNING " + _POSTGRES_CHECKPOINT_COLUMNS,
                        _postgres_checkpoint_params(checkpoint),
                    )
                persisted = cursor.fetchone()
                if persisted is None:
                    raise ReplayCheckpointCorruptionError(
                        "PostgreSQL replay checkpoint write returned no durable row"
                    )
                result = _checkpoint_from_postgres_row(persisted)
                if result != checkpoint:
                    raise ReplayCheckpointCorruptionError(
                        "PostgreSQL replay checkpoint differs after durable write"
                    )
                return result

    def get_checkpoint(
        self,
        checkpoint_id: str,
        *,
        tenant_id: str | None = None,
    ) -> ReplayCheckpoint | None:
        normalized_id = _required_text(checkpoint_id, "checkpoint_id")
        with self._transaction(read_only=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT " + _POSTGRES_CHECKPOINT_COLUMNS + " "
                    "FROM event_replay_checkpoints WHERE checkpoint_id = %s "
                    "AND tenant_scope = %s",
                    (normalized_id, _tenant_scope(tenant_id)),
                )
                row = cursor.fetchone()
        return None if row is None else _checkpoint_from_postgres_row(row)

    @contextmanager
    def _transaction(self, *, read_only: bool = False) -> Iterator[Any]:
        connection: Any | None = None
        try:
            connection = self._connection_factory()
            if getattr(connection, "autocommit", False):
                connection.autocommit = False
            if read_only:
                with connection.cursor() as cursor:
                    cursor.execute("SET TRANSACTION READ ONLY")
            yield connection
            connection.commit()
        except (ReplayCheckpointCollisionError, ReplayCheckpointCorruptionError):
            if connection is not None:
                connection.rollback()
            raise
        except BaseException as exc:
            if connection is not None:
                try:
                    connection.rollback()
                except BaseException:
                    pass
            _reraise_postgres_exception(exc)
        finally:
            if connection is not None:
                try:
                    connection.close()
                except BaseException:
                    pass


_POSTGRES_CHECKPOINT_COLUMNS = """
    checkpoint_id,
    tenant_id,
    mode,
    source_stream_id,
    last_sequence,
    source_high_watermark,
    runtime_version,
    schema_catalog_version,
    reducer_id,
    reducer_version,
    parent_checkpoint_id,
    history_checksum,
    checkpoint_checksum,
    checkpoint_json
"""


def _validated_checkpoint(checkpoint: ReplayCheckpoint) -> ReplayCheckpoint:
    if not isinstance(checkpoint, ReplayCheckpoint):
        raise TypeError("checkpoint must be ReplayCheckpoint")
    try:
        checkpoint.verify_integrity()
    except EventIntegrityError as exc:
        raise ReplayCheckpointCorruptionError(
            "replay checkpoint failed checksum verification before storage"
        ) from exc
    return checkpoint


def _validate_checkpoint_replacement(
    existing: ReplayCheckpoint,
    candidate: ReplayCheckpoint,
) -> None:
    if _checkpoint_immutable_identity(existing) != _checkpoint_immutable_identity(
        candidate
    ):
        raise ReplayCheckpointCollisionError(
            candidate.checkpoint_id,
            reason="immutable checkpoint identity changed",
        )
    if candidate.last_sequence < existing.last_sequence:
        raise ReplayCheckpointCollisionError(
            candidate.checkpoint_id,
            reason="last_sequence cannot move backwards",
        )
    if candidate.last_sequence == existing.last_sequence and candidate != existing:
        raise ReplayCheckpointCollisionError(
            candidate.checkpoint_id,
            reason="equal sequence requires an exact checkpoint checksum match",
        )


def _checkpoint_immutable_identity(checkpoint: ReplayCheckpoint) -> tuple[Any, ...]:
    return (
        checkpoint.checkpoint_id,
        checkpoint.tenant_id,
        checkpoint.mode,
        checkpoint.source_stream_id,
        checkpoint.source_high_watermark,
        checkpoint.runtime_version,
        checkpoint.schema_catalog_version,
        checkpoint.reducer_id,
        checkpoint.reducer_version,
        checkpoint.parent_checkpoint_id,
    )


def _checkpoint_json(checkpoint: ReplayCheckpoint) -> str:
    return stable_json_dumps(checkpoint.to_dict())


def _sqlite_checkpoint_params(checkpoint: ReplayCheckpoint) -> tuple[Any, ...]:
    return (
        checkpoint.checkpoint_id,
        _tenant_scope(checkpoint.tenant_id),
        checkpoint.tenant_id,
        checkpoint.mode.value,
        checkpoint.source_stream_id,
        checkpoint.last_sequence,
        checkpoint.source_high_watermark,
        checkpoint.runtime_version,
        checkpoint.schema_catalog_version,
        checkpoint.reducer_id or "",
        checkpoint.reducer_id,
        checkpoint.reducer_version,
        checkpoint.parent_checkpoint_id or "",
        checkpoint.parent_checkpoint_id,
        checkpoint.history_checksum,
        checkpoint.checkpoint_checksum,
        _checkpoint_json(checkpoint),
    )


def _postgres_checkpoint_params(checkpoint: ReplayCheckpoint) -> tuple[Any, ...]:
    return (
        checkpoint.checkpoint_id,
        checkpoint.tenant_id,
        checkpoint.mode.value,
        checkpoint.source_stream_id,
        checkpoint.last_sequence,
        checkpoint.source_high_watermark,
        checkpoint.runtime_version,
        checkpoint.schema_catalog_version,
        checkpoint.reducer_id,
        checkpoint.reducer_version,
        checkpoint.parent_checkpoint_id,
        checkpoint.history_checksum,
        checkpoint.checkpoint_checksum,
        _checkpoint_json(checkpoint),
    )


def _checkpoint_from_sqlite_row(row: Mapping[str, Any]) -> ReplayCheckpoint:
    checkpoint = _checkpoint_from_json(row["checkpoint_json"])
    expected = (
        checkpoint.checkpoint_id,
        _tenant_scope(checkpoint.tenant_id),
        checkpoint.tenant_id,
        checkpoint.mode.value,
        checkpoint.source_stream_id,
        checkpoint.last_sequence,
        checkpoint.source_high_watermark,
        checkpoint.runtime_version,
        checkpoint.schema_catalog_version,
        checkpoint.reducer_id or "",
        checkpoint.reducer_id,
        checkpoint.reducer_version,
        checkpoint.parent_checkpoint_id or "",
        checkpoint.parent_checkpoint_id,
        checkpoint.history_checksum,
        checkpoint.checkpoint_checksum,
    )
    actual = tuple(
        row[name]
        for name in (
            "checkpoint_id",
            "tenant_scope",
            "tenant_id",
            "mode",
            "source_stream_id",
            "last_sequence",
            "source_high_watermark",
            "runtime_version",
            "schema_catalog_version",
            "reducer_scope",
            "reducer_id",
            "reducer_version",
            "parent_checkpoint_scope",
            "parent_checkpoint_id",
            "history_checksum",
            "checkpoint_checksum",
        )
    )
    if actual != expected:
        raise ReplayCheckpointCorruptionError(
            "SQLite replay checkpoint indexes disagree with checkpoint JSON"
        )
    return checkpoint


def _checkpoint_from_postgres_row(row: tuple[Any, ...]) -> ReplayCheckpoint:
    checkpoint = _checkpoint_from_json(row[13])
    expected = (
        checkpoint.checkpoint_id,
        checkpoint.tenant_id,
        checkpoint.mode.value,
        checkpoint.source_stream_id,
        checkpoint.last_sequence,
        checkpoint.source_high_watermark,
        checkpoint.runtime_version,
        checkpoint.schema_catalog_version,
        checkpoint.reducer_id,
        checkpoint.reducer_version,
        checkpoint.parent_checkpoint_id,
        checkpoint.history_checksum,
        checkpoint.checkpoint_checksum,
    )
    if tuple(row[:13]) != expected:
        raise ReplayCheckpointCorruptionError(
            "PostgreSQL replay checkpoint indexes disagree with checkpoint JSON"
        )
    return checkpoint


def _checkpoint_from_json(value: Any) -> ReplayCheckpoint:
    try:
        if isinstance(value, str):
            payload = json_loads(value)
        elif isinstance(value, Mapping):
            payload = dict(value)
        else:
            payload = json.loads(str(value))
        if not isinstance(payload, Mapping):
            raise TypeError("checkpoint JSON must be an object")
        checkpoint = ReplayCheckpoint.from_dict(payload)
        checkpoint.verify_integrity()
        return checkpoint
    except (
        EventIntegrityError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise ReplayCheckpointCorruptionError(
            "stored replay checkpoint cannot be decoded or verified"
        ) from exc


def _tenant_scope(tenant_id: str | None) -> str:
    if tenant_id is None:
        return ""
    return _required_text(tenant_id, "tenant_id")


def _is_missing_psycopg(exc: ModuleNotFoundError) -> bool:
    missing = str(exc.name or "")
    return missing == "psycopg" or missing.startswith("psycopg.")


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def _map_sqlite_error(exc: sqlite3.Error, *, operation: str) -> EventStoreError:
    message = str(exc).lower()
    code = getattr(exc, "sqlite_errorcode", None)
    primary_code = code & 0xFF if isinstance(code, int) else None
    if primary_code == sqlite3.SQLITE_FULL or "database or disk is full" in message:
        return EventStoreCapacityError(f"{operation}: durable capacity is exhausted")
    if primary_code in {sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB} or any(
        marker in message
        for marker in (
            "database disk image is malformed",
            "file is not a database",
            "database corruption",
        )
    ):
        return ReplayCheckpointCorruptionError(f"{operation}: SQLite store is corrupt")
    if primary_code in {
        sqlite3.SQLITE_BUSY,
        sqlite3.SQLITE_LOCKED,
        sqlite3.SQLITE_READONLY,
        sqlite3.SQLITE_CANTOPEN,
        sqlite3.SQLITE_IOERR,
        sqlite3.SQLITE_PERM,
        sqlite3.SQLITE_AUTH,
    } or any(
        marker in message
        for marker in (
            "database is locked",
            "database table is locked",
            "readonly database",
            "read-only database",
            "unable to open database file",
            "disk i/o error",
            "permission denied",
        )
    ):
        return EventStoreUnavailableError(f"{operation}: durable store is unavailable")
    return ReplayCheckpointCorruptionError(f"{operation}: SQLite operation failed")


def _reraise_postgres_exception(exc: BaseException) -> NoReturn:
    if isinstance(
        exc,
        (
            ReplayCheckpointCollisionError,
            ReplayCheckpointCorruptionError,
            EventContractError,
            ValueError,
            TypeError,
        ),
    ):
        raise exc
    if isinstance(exc, EventStoreError):
        raise exc
    try:
        import psycopg
    except ImportError:
        raise EventStoreUnavailableError(
            "PostgreSQL replay checkpoint adapter requires psycopg"
        ) from exc
    if not isinstance(exc, psycopg.Error):
        raise exc
    sqlstate = str(getattr(exc, "sqlstate", "") or "")
    if sqlstate in {"53100", "53200", "53400"}:
        raise EventStoreCapacityError(
            "PostgreSQL replay checkpoint capacity is exhausted"
        ) from exc
    if (
        isinstance(exc, (psycopg.OperationalError, psycopg.InterfaceError))
        or sqlstate.startswith("08")
        or sqlstate in {"53300", "57P01", "57P02", "57P03"}
    ):
        raise EventStoreUnavailableError(
            "PostgreSQL replay checkpoint store is unavailable"
        ) from exc
    if sqlstate in {"23505", "23514", "P0001"}:
        checkpoint_id = _checkpoint_id_from_postgres_failure(exc)
        raise ReplayCheckpointCollisionError(
            checkpoint_id,
            reason="database rejected an incompatible checkpoint replacement",
        ) from exc
    if sqlstate == "23503":
        raise ReplayCheckpointCorruptionError(
            "PostgreSQL replay checkpoint source stream is missing"
        ) from exc
    raise ReplayCheckpointCorruptionError(
        "PostgreSQL replay checkpoint operation failed"
    ) from exc


def _checkpoint_id_from_postgres_failure(exc: BaseException) -> str:
    diagnostic = getattr(exc, "diag", None)
    detail = str(getattr(diagnostic, "message_detail", "") or "")
    marker = "(checkpoint_id)=("
    start = detail.find(marker)
    if start < 0:
        return "unknown-checkpoint"
    value_start = start + len(marker)
    value_end = detail.find(")", value_start)
    if value_end <= value_start:
        return "unknown-checkpoint"
    candidate = detail[value_start:value_end].strip()
    return candidate or "unknown-checkpoint"


__all__ = [
    "PostgresReplayCheckpointStore",
    "SQLiteReplayCheckpointStore",
]
