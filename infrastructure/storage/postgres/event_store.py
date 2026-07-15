from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from pathlib import Path
from typing import Any, Callable

import psycopg

from framework.events.errors import EventIdentityCollisionError, EventStoreCorruptionError
from framework.shared.json import stable_json_dumps
from infrastructure.storage.postgres.dsn import normalize_dsn

from infrastructure.storage.events.models import EventRecord


ConnectionFactory = Callable[[], Any]


class PostgresEventStore:
    def __init__(self, dsn: str, *, connection_factory: ConnectionFactory | None = None) -> None:
        self.dsn = dsn
        self._connection_factory = connection_factory or (lambda: psycopg.connect(normalize_dsn(dsn)))

    def append_event(self, event: EventRecord) -> int:
        _validate_event(event)
        with self._connection_factory() as connection:
            transaction_factory = getattr(connection, "transaction", None)
            if callable(transaction_factory):
                # An explicit transaction remains effective even if a caller
                # supplied an autocommit connection.
                with transaction_factory():
                    return self._append_event_in_transaction(connection, event)
            offset = self._append_event_in_transaction(connection, event)
            connection.commit()
            return offset

    def _append_event_in_transaction(self, connection: Any, event: EventRecord) -> int:
        allocation_sql = """
        SELECT COALESCE(MAX(event_offset), -1) + 1
        FROM workflow_events
        WHERE run_id = %s
        """
        insert_sql = """
        INSERT INTO workflow_events (
            event_id, run_id, event_offset, event_type, timestamp,
            workflow_id, step_id, task_id, agent_id, tool_call_id, request_id,
            severity, trace_id, redacted, payload, metadata
        )
        VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s::jsonb, %s::jsonb
        )
        ON CONFLICT (event_id) DO NOTHING
        RETURNING event_offset
        """
        with connection.cursor() as cursor:
            _cursor_execute(cursor, "SET TRANSACTION ISOLATION LEVEL READ COMMITTED", ())
            # Serialize legacy writers per run inside the same transaction.
            # The canonical migration replaces this compatibility path with a
            # stream-counter row, but this removes the unsafe COUNT/INSERT split
            # immediately without taking a global table lock.
            _cursor_execute(
                cursor,
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (event.run_id,),
            )
            _cursor_execute(cursor, allocation_sql, (event.run_id,))
            row = cursor.fetchone()
            offset = int(row[0]) if row else 0
            params = (
                event.event_id,
                event.run_id,
                offset,
                event.event_type,
                event.timestamp,
                event.workflow_id,
                event.step_id,
                event.task_id,
                event.agent_id,
                event.tool_call_id,
                event.request_id,
                event.severity,
                event.trace_id,
                event.redacted,
                _json(event.payload),
                _json(event.metadata),
            )
            _cursor_execute(cursor, insert_sql, params)
            inserted = cursor.fetchone()
            if inserted is None:
                _cursor_execute(
                    cursor,
                    _select_existing_sql(),
                    (event.event_id,),
                )
                existing_row = cursor.fetchone()
                if existing_row is None:
                    raise EventStoreCorruptionError(
                        "duplicate event id was reported but no committed row exists"
                    )
                existing_offset = int(existing_row[0])
                existing_event = _event_from_row(existing_row[1:])
                if _legacy_identity_projection(existing_event) != _legacy_identity_projection(
                    event
                ):
                    raise EventIdentityCollisionError(event.event_id)
                offset = existing_offset
        return offset

    def list_by_run(self, run_id: str, limit: int | None = None) -> list[EventRecord]:
        _validate_id(run_id, "run_id")
        if limit is not None and limit <= 0:
            raise ValueError("limit must be greater than zero")
        sql = _select_sql("WHERE run_id = %s")
        params: tuple[Any, ...] = (run_id,)
        if limit is not None:
            sql += "\nLIMIT %s"
            params = (run_id, limit)
        return self._fetch_events(sql, params)

    def list_by_step(self, run_id: str, step_id: str) -> list[EventRecord]:
        _validate_id(run_id, "run_id")
        _validate_id(step_id, "step_id")
        return self._fetch_events(
            _select_sql("WHERE run_id = %s AND step_id = %s"),
            (run_id, step_id),
        )

    def filter_by_type(
        self,
        run_id: str,
        event_type: str,
        *,
        limit: int | None = None,
    ) -> list[EventRecord]:
        _validate_id(run_id, "run_id")
        _validate_required(event_type, "event_type")
        if limit is not None and limit <= 0:
            raise ValueError("limit must be greater than zero")
        sql = _select_sql("WHERE run_id = %s AND event_type = %s")
        params: tuple[Any, ...] = (run_id, event_type)
        if limit is not None:
            sql += "\nLIMIT %s"
            params = (run_id, event_type, limit)
        return self._fetch_events(sql, params)

    async def stream_from_offset(self, run_id: str, offset: int) -> AsyncIterator[EventRecord]:
        _validate_id(run_id, "run_id")
        if offset < 0:
            raise ValueError("offset must be greater than or equal to zero")
        events = self._fetch_events(
            _select_sql("WHERE run_id = %s AND event_offset >= %s"),
            (run_id, offset),
        )
        for event in events:
            yield event

    def _fetch_events(self, sql: str, params: tuple[Any, ...]) -> list[EventRecord]:
        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                _cursor_execute(cursor, sql, params)
                return [_event_from_row(row) for row in cursor.fetchall()]


def _select_sql(where_clause: str) -> str:
    return f"""
        SELECT
            event_id, run_id, event_type, timestamp, workflow_id, step_id,
            task_id, agent_id, tool_call_id, request_id, payload, severity,
            trace_id, redacted, metadata
        FROM workflow_events
        {where_clause}
        ORDER BY event_offset ASC
    """


def _select_existing_sql() -> str:
    return """
        SELECT
            event_offset,
            event_id, run_id, event_type, timestamp, workflow_id, step_id,
            task_id, agent_id, tool_call_id, request_id, payload, severity,
            trace_id, redacted, metadata
        FROM workflow_events
        WHERE event_id = %s
    """


def _event_from_row(row: tuple[Any, ...]) -> EventRecord:
    return EventRecord(
        event_id=str(row[0]),
        run_id=str(row[1]),
        event_type=str(row[2]),
        timestamp=_timestamp(row[3]),
        workflow_id=_optional_str(row[4]),
        step_id=_optional_str(row[5]),
        task_id=_optional_str(row[6]),
        agent_id=_optional_str(row[7]),
        tool_call_id=_optional_str(row[8]),
        request_id=_optional_str(row[9]),
        payload=_dict(row[10]),
        severity=str(row[11] or "info"),
        trace_id=_optional_str(row[12]),
        redacted=bool(row[13]),
        metadata=_dict(row[14]),
    )


def _json(value: Any) -> str:
    return stable_json_dumps(value or {})


def _cursor_execute(cursor: Any, sql: str, params: tuple[Any, ...]) -> Any:
    return cursor.execute(sql, params)


def _dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        payload = json.loads(value)
        if not isinstance(payload, dict):
            raise EventStoreCorruptionError("stored event JSONB value must be an object")
        return payload
    try:
        return dict(value)
    except (TypeError, ValueError) as exc:
        raise EventStoreCorruptionError(
            "stored event JSONB value must be an object"
        ) from exc


def _legacy_identity_projection(event: EventRecord) -> str:
    return stable_json_dumps(event.to_dict())


def _timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _validate_event(event: EventRecord) -> None:
    _validate_id(event.run_id, "run_id")
    if not event.event_id:
        raise ValueError("event_id is required")
    if not event.event_type:
        raise ValueError("event_type is required")
    if event.step_id is not None:
        _validate_id(event.step_id, "step_id")


def _validate_id(value: str, label: str) -> None:
    if not value:
        raise ValueError(f"{label} is required")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 1:
        raise ValueError(f"invalid {label}: {value}")


def _validate_required(value: str, label: str) -> None:
    if not value:
        raise ValueError(f"{label} is required")
