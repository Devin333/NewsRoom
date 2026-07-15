from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from datetime import datetime
from hashlib import sha256
from hmac import compare_digest
from pathlib import Path
from typing import Any, Callable

from framework.events.migration import MigrationSourceKind, MigrationSourceRecord


ConnectionFactory = Callable[[], Any]

_POSTGRES_TABLES = frozenset({"workflow_events", "durable_events"})
_WORKFLOW_EVENTS_QUERY = """
    SELECT
        event_offset, event_id, run_id, event_type, timestamp, workflow_id,
        step_id, task_id, agent_id, tool_call_id, request_id, payload,
        severity, trace_id, redacted, metadata
    FROM workflow_events
    ORDER BY run_id ASC, event_offset ASC, event_id ASC
"""
_DURABLE_EVENTS_QUERY = """
    SELECT
        event_id, tenant_id, stream_id, stream_sequence, envelope_schema,
        event_type, data_schema, source, subject, occurred_at, observed_at,
        correlation_id, causation_id, business_context, producer,
        trace_context, security_classification, content_type, payload,
        payload_ref, extensions, content_checksum, record_checksum
    FROM durable_events
    ORDER BY tenant_scope ASC, stream_id ASC, stream_sequence ASC, event_id ASC
"""


class MigrationSourceReadError(RuntimeError):
    """A bounded source error that never includes source contents or a DSN."""

    def __init__(self, source_kind: MigrationSourceKind | str) -> None:
        self.source_kind = MigrationSourceKind(source_kind)
        super().__init__(f"unable to read {self.source_kind.value} migration source")


def iter_jsonl_records(
    paths: Iterable[str | Path],
    *,
    source_kind: MigrationSourceKind | str,
    expected_fingerprints: Mapping[str, str] | None = None,
) -> Iterator[MigrationSourceRecord]:
    actual_kind = MigrationSourceKind(source_kind)
    try:
        for path in _expand_files(paths, suffix=".jsonl"):
            yield from _iter_jsonl_file(
                path,
                source_kind=actual_kind,
                expected_fingerprint=_expected_fingerprint(
                    path,
                    expected_fingerprints,
                    source_kind=actual_kind,
                ),
            )
    except MigrationSourceReadError:
        raise
    except OSError as exc:
        raise MigrationSourceReadError(actual_kind) from exc


def iter_checkpoint_records(
    paths: Iterable[str | Path],
    *,
    expected_fingerprints: Mapping[str, str] | None = None,
) -> Iterator[MigrationSourceRecord]:
    try:
        for path in _expand_files(paths, suffix=".json"):
            yield from _iter_checkpoint_file(
                path,
                expected_fingerprint=_expected_fingerprint(
                    path,
                    expected_fingerprints,
                    source_kind=MigrationSourceKind.CHECKPOINT,
                ),
            )
    except MigrationSourceReadError:
        raise
    except OSError as exc:
        raise MigrationSourceReadError(MigrationSourceKind.CHECKPOINT) from exc


def fingerprint_source_paths(
    paths: Iterable[str | Path],
    *,
    suffix: str,
    source_kind: MigrationSourceKind | str = MigrationSourceKind.LEGACY_RUN_JSONL,
) -> dict[str, str]:
    """Hash source bytes without opening files for write or following mutations."""

    actual_kind = MigrationSourceKind(source_kind)
    fingerprints: dict[str, str] = {}
    try:
        for raw_path in paths:
            path = Path(raw_path)
            if not path.exists():
                raise FileNotFoundError(path)
            if path.is_file() and path.suffix.lower() != suffix:
                raise ValueError("migration source file extension does not match source type")
            candidates = [path] if path.is_file() else sorted(path.rglob(f"*{suffix}"))
            for candidate in candidates:
                if not candidate.is_file() or candidate.suffix.lower() != suffix:
                    continue
                resolved = candidate.resolve(strict=True)
                fingerprints[str(resolved)] = _sha256_file(resolved)
    except OSError as exc:
        raise MigrationSourceReadError(actual_kind) from exc
    return dict(sorted(fingerprints.items()))


class PostgresEventMigrationReader:
    """Read legacy and canonical PostgreSQL rows in a rollback-only transaction."""

    def __init__(
        self,
        dsn: str,
        *,
        connection_factory: ConnectionFactory | None = None,
        batch_size: int = 500,
    ) -> None:
        if not isinstance(dsn, str) or not dsn.strip():
            raise ValueError("PostgreSQL migration source requires a DSN")
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size <= 0:
            raise ValueError("PostgreSQL migration batch_size must be positive")
        self._connection_factory = connection_factory or (
            lambda: _connect_postgres(dsn)
        )
        self._batch_size = batch_size

    def iter_records(self) -> Iterator[MigrationSourceRecord]:
        connection: Any | None = None
        try:
            connection = self._connection_factory()
            with connection.cursor() as cursor:
                cursor.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
                tables = _available_event_tables(cursor)
                if "workflow_events" in tables:
                    yield from self._read_workflow_events(cursor)
                if "durable_events" in tables:
                    yield from self._read_durable_events(cursor)
        except Exception as exc:
            raise MigrationSourceReadError(MigrationSourceKind.POSTGRESQL_ROW) from exc
        finally:
            if connection is not None:
                _rollback_and_close(connection)

    def _read_workflow_events(self, cursor: Any) -> Iterator[MigrationSourceRecord]:
        cursor.execute(_WORKFLOW_EVENTS_QUERY)
        for row in _batched_rows(cursor, batch_size=self._batch_size):
            offset = int(row[0])
            run_id = str(row[2])
            yield MigrationSourceRecord(
                source_kind=MigrationSourceKind.POSTGRESQL_ROW,
                location=f"postgresql:workflow_events:{run_id}:{offset}",
                value={
                    "event_id": str(row[1]),
                    "run_id": run_id,
                    "event_type": str(row[3]),
                    "timestamp": _time_value(row[4]),
                    "workflow_id": _optional_str(row[5]),
                    "step_id": _optional_str(row[6]),
                    "task_id": _optional_str(row[7]),
                    "agent_id": _optional_str(row[8]),
                    "tool_call_id": _optional_str(row[9]),
                    "request_id": _optional_str(row[10]),
                    "payload": _json_object(row[11]),
                    "severity": str(row[12] or "info"),
                    "trace_id": _optional_str(row[13]),
                    "redacted": bool(row[14]),
                    "metadata": _json_object(row[15]),
                },
            )

    def _read_durable_events(self, cursor: Any) -> Iterator[MigrationSourceRecord]:
        cursor.execute(_DURABLE_EVENTS_QUERY)
        for row in _batched_rows(cursor, batch_size=self._batch_size):
            event_id = str(row[0])
            yield MigrationSourceRecord(
                source_kind=MigrationSourceKind.POSTGRESQL_ROW,
                location=f"postgresql:durable_events:{event_id}",
                value={
                    "event_id": event_id,
                    "tenant_id": _optional_str(row[1]),
                    "stream_id": str(row[2]),
                    "stream_sequence": int(row[3]),
                    "envelope_schema": str(row[4]),
                    "event_type": str(row[5]),
                    "data_schema": str(row[6]),
                    "source": str(row[7]),
                    "subject": _optional_str(row[8]),
                    "occurred_at": _time_value(row[9]),
                    "observed_at": _time_value(row[10]),
                    "correlation_id": _optional_str(row[11]),
                    "causation_id": _optional_str(row[12]),
                    "business_context": _json_object(row[13]),
                    "producer": _json_object(row[14]),
                    "trace": _optional_json_object(row[15]),
                    "security_classification": str(row[16]),
                    "content_type": str(row[17]),
                    "payload": _optional_json_object(row[18]),
                    "payload_ref": _optional_json_object(row[19]),
                    "extensions": _json_object(row[20]),
                    "content_checksum": str(row[21]),
                    "record_checksum": str(row[22]),
                },
            )


def _iter_jsonl_file(
    path: Path,
    *,
    source_kind: MigrationSourceKind,
    expected_fingerprint: str | None = None,
) -> Iterator[MigrationSourceRecord]:
    digest = sha256()
    exhausted = False
    with path.open("rb") as handle:
        try:
            for line_number, raw_line in enumerate(handle, start=1):
                digest.update(raw_line)
                location = f"{path}:{line_number}"
                try:
                    line = raw_line.decode("utf-8-sig" if line_number == 1 else "utf-8")
                except UnicodeDecodeError:
                    yield MigrationSourceRecord.issue(source_kind, location, "invalid_utf8")
                    continue
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    yield MigrationSourceRecord.issue(source_kind, location, "invalid_json")
                    continue
                if not isinstance(value, Mapping):
                    yield MigrationSourceRecord.issue(
                        source_kind,
                        location,
                        "invalid_record_type",
                    )
                    continue
                try:
                    yield MigrationSourceRecord(
                        source_kind=source_kind,
                        location=location,
                        value=value,
                    )
                except (TypeError, ValueError):
                    yield MigrationSourceRecord.issue(
                        source_kind,
                        location,
                        "unsupported_legacy_mapping",
                    )
            exhausted = True
        finally:
            if not exhausted:
                while chunk := handle.read(1024 * 1024):
                    digest.update(chunk)
            _verify_expected_fingerprint(
                digest.hexdigest(),
                expected_fingerprint,
                source_kind=source_kind,
            )


def _iter_checkpoint_file(
    path: Path,
    *,
    expected_fingerprint: str | None = None,
) -> Iterator[MigrationSourceRecord]:
    try:
        raw_value = path.read_bytes()
        _verify_expected_fingerprint(
            sha256(raw_value).hexdigest(),
            expected_fingerprint,
            source_kind=MigrationSourceKind.CHECKPOINT,
        )
        value = json.loads(raw_value.decode("utf-8-sig"))
    except (json.JSONDecodeError, UnicodeError):
        yield MigrationSourceRecord.issue(
            MigrationSourceKind.CHECKPOINT,
            str(path),
            "invalid_json",
        )
        return
    if not isinstance(value, Mapping):
        yield MigrationSourceRecord.issue(
            MigrationSourceKind.CHECKPOINT,
            str(path),
            "invalid_record_type",
        )
        return
    if _is_checkpoint_record(value):
        yield MigrationSourceRecord(
            source_kind=MigrationSourceKind.CHECKPOINT,
            location=str(path),
            value=value,
        )
        return
    found = False
    for name in sorted(value, key=str):
        item = value[name]
        if not isinstance(item, Mapping) or not _is_checkpoint_record(item):
            continue
        found = True
        yield MigrationSourceRecord(
            source_kind=MigrationSourceKind.CHECKPOINT,
            location=f"{path}#{name}",
            value=item,
        )
    if not found:
        yield MigrationSourceRecord.issue(
            MigrationSourceKind.CHECKPOINT,
            str(path),
            "unsupported_legacy_mapping",
        )


def _is_checkpoint_record(value: Mapping[str, Any]) -> bool:
    if "checkpoint_id" in value and "run_id" in value:
        return True
    payload = value.get("payload")
    return isinstance(payload, Mapping) and "checkpoint_id" in payload and "run_id" in payload


def _expand_files(paths: Iterable[str | Path], *, suffix: str) -> Iterator[Path]:
    discovered: set[Path] = set()
    for raw_path in paths:
        path = Path(raw_path)
        if not path.exists():
            raise FileNotFoundError(path)
        if path.is_file() and path.suffix.lower() != suffix:
            raise ValueError("migration source file extension does not match source type")
        candidates = [path] if path.is_file() else sorted(path.rglob(f"*{suffix}"))
        for candidate in candidates:
            if not candidate.is_file() or candidate.suffix.lower() != suffix:
                continue
            resolved = candidate.resolve(strict=True)
            if resolved in discovered:
                continue
            discovered.add(resolved)
            yield resolved


def _available_event_tables(cursor: Any) -> set[str]:
    cursor.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = current_schema()
          AND table_name IN ('workflow_events', 'durable_events')
        ORDER BY table_name ASC
        """
    )
    tables = {str(row[0]) for row in cursor.fetchall()}
    return tables & _POSTGRES_TABLES


def _batched_rows(cursor: Any, *, batch_size: int) -> Iterator[tuple[Any, ...]]:
    fetchmany = getattr(cursor, "fetchmany", None)
    if not callable(fetchmany):
        yield from cursor.fetchall()
        return
    while True:
        rows = fetchmany(batch_size)
        if not rows:
            return
        yield from rows


def _json_object(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        decoded = json.loads(value)
        if isinstance(decoded, Mapping):
            return dict(decoded)
    raise TypeError("PostgreSQL event JSON value must be an object")


def _optional_json_object(value: Any) -> dict[str, Any] | None:
    return None if value is None else _json_object(value)


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _time_value(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.isoformat()
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


def _rollback_and_close(connection: Any) -> None:
    try:
        rollback = getattr(connection, "rollback", None)
        if callable(rollback):
            rollback()
    finally:
        close = getattr(connection, "close", None)
        if callable(close):
            close()


def _connect_postgres(dsn: str) -> Any:
    try:
        import psycopg
    except ImportError as exc:
        raise MigrationSourceReadError(MigrationSourceKind.POSTGRESQL_ROW) from exc
    return psycopg.connect(_normalize_dsn(dsn))


def _normalize_dsn(dsn: str) -> str:
    return dsn.strip().removeprefix("jdbc:")


def _sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _expected_fingerprint(
    path: Path,
    fingerprints: Mapping[str, str] | None,
    *,
    source_kind: MigrationSourceKind,
) -> str | None:
    if fingerprints is None:
        return None
    expected = fingerprints.get(str(path.resolve(strict=True)))
    if expected is None:
        raise MigrationSourceReadError(source_kind)
    return expected


def _verify_expected_fingerprint(
    actual: str,
    expected: str | None,
    *,
    source_kind: MigrationSourceKind,
) -> None:
    if expected is not None and not compare_digest(actual, expected):
        raise MigrationSourceReadError(source_kind)


__all__ = [
    "MigrationSourceReadError",
    "PostgresEventMigrationReader",
    "fingerprint_source_paths",
    "iter_checkpoint_records",
    "iter_jsonl_records",
]
