from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import psycopg

from infrastructure.storage.events.models import EventRecord


ConnectionFactory = Callable[[], Any]


class PostgresEventStore:
    def __init__(self, dsn: str, *, connection_factory: ConnectionFactory | None = None) -> None:
        self.dsn = dsn
        self._connection_factory = connection_factory or (lambda: psycopg.connect(dsn))

    def append_event(self, event: EventRecord) -> int:
        _validate_event(event)
        offset = self._next_offset(event.run_id)
        sql = """
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
        """
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
        self._execute(sql, params)
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

    def _next_offset(self, run_id: str) -> int:
        sql = "SELECT COUNT(*) FROM workflow_events WHERE run_id = %s"
        row = self._fetch_one(sql, (run_id,))
        return int(row[0]) if row else 0

    def _execute(self, sql: str, params: tuple[Any, ...]) -> None:
        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                _cursor_execute(cursor, sql, params)
            connection.commit()

    def _fetch_one(self, sql: str, params: tuple[Any, ...]) -> tuple[Any, ...] | None:
        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                _cursor_execute(cursor, sql, params)
                return cursor.fetchone()

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
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)


def _cursor_execute(cursor: Any, sql: str, params: tuple[Any, ...]) -> Any:
    return cursor.execute(sql, params)


def _dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        payload = json.loads(value)
        return payload if isinstance(payload, dict) else {}
    return dict(value)


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
