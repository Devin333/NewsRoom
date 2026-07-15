from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import pytest

from infrastructure.storage.events import EventRecord as StorageEventRecord
from framework.events.errors import EventIdentityCollisionError
from infrastructure.storage.postgres import PostgresEventStore


class _SqlShapeCursor:
    def __init__(self, connection: _SqlShapeConnection) -> None:
        self._connection = connection

    def __enter__(self) -> _SqlShapeCursor:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False

    def execute(self, sql: Any, params: Any = None) -> _SqlShapeCursor:
        self._connection.calls.append((str(sql), params))
        return self

    def fetchone(self) -> tuple[int]:
        return (1,)

    def fetchall(self) -> list[tuple[Any, ...]]:
        return []


class _SqlShapeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.commits = 0
        self.context_entries = 0
        self.context_exits = 0

    def __enter__(self) -> _SqlShapeConnection:
        self.context_entries += 1
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        self.context_exits += 1
        return False

    def cursor(self) -> _SqlShapeCursor:
        return _SqlShapeCursor(self)

    def commit(self) -> None:
        self.commits += 1


class _ConnectionFactory:
    def __init__(self) -> None:
        self.connections: list[_SqlShapeConnection] = []

    def __call__(self) -> _SqlShapeConnection:
        connection = _SqlShapeConnection()
        self.connections.append(connection)
        return connection


def _event() -> StorageEventRecord:
    return StorageEventRecord(
        event_id="event-adversarial-1",
        run_id="run-adversarial-1",
        event_type="step_succeeded",
        timestamp=datetime(2026, 7, 15, 1, 2, tzinfo=UTC),
        step_id="collect",
        payload={"safe": "visible"},
    )


def _all_sql(factory: _ConnectionFactory) -> list[str]:
    return [
        sql
        for connection in factory.connections
        for sql, _params in connection.calls
    ]


def test_append_sequence_allocation_never_uses_count_star() -> None:
    """SQL-shape guard only; real PostgreSQL concurrency remains a separate gate."""
    factory = _ConnectionFactory()
    store = PostgresEventStore(
        "postgresql://example",
        connection_factory=factory,
    )

    store.append_event(_event())

    assert not any(
        re.search(r"\bCOUNT\s*\(\s*\*\s*\)", sql, flags=re.IGNORECASE)
        for sql in _all_sql(factory)
    )


def test_append_allocates_sequence_and_inserts_event_in_one_transaction() -> None:
    """Proves connection/SQL shape, not real concurrent-writer correctness."""
    factory = _ConnectionFactory()
    store = PostgresEventStore(
        "postgresql://example",
        connection_factory=factory,
    )

    store.append_event(_event())

    assert len(factory.connections) == 1
    connection = factory.connections[0]
    normalized_sql = [" ".join(sql.upper().split()) for sql, _ in connection.calls]
    event_insert_indexes = [
        index
        for index, sql in enumerate(normalized_sql)
        if "INSERT INTO WORKFLOW_EVENTS" in sql
    ]
    assert len(event_insert_indexes) == 1
    insert_index = event_insert_indexes[0]
    allocation_and_insert_sql = normalized_sql[: insert_index + 1]
    assert any(
        marker in sql
        for sql in allocation_and_insert_sql
        for marker in (
            "FOR UPDATE",
            "RETURNING",
            "PG_ADVISORY_XACT_LOCK",
            "LOCK TABLE",
        )
    )
    assert connection.context_entries == 1
    assert connection.context_exits == 1
    assert connection.commits == 1


class _DuplicateCursor(_SqlShapeCursor):
    def __init__(self, connection: _DuplicateConnection) -> None:
        super().__init__(connection)
        self._duplicate_connection = connection
        self._last_sql = ""

    def execute(self, sql: Any, params: Any = None) -> _DuplicateCursor:
        self._last_sql = str(sql)
        super().execute(sql, params)
        return self

    def fetchone(self) -> tuple[Any, ...] | None:
        normalized = " ".join(self._last_sql.upper().split())
        if "MAX(EVENT_OFFSET)" in normalized:
            return (10,)
        if "INSERT INTO WORKFLOW_EVENTS" in normalized:
            return None
        if "WHERE EVENT_ID = %S" in normalized:
            event = self._duplicate_connection.existing_event
            return (
                self._duplicate_connection.existing_offset,
                event.event_id,
                event.run_id,
                event.event_type,
                event.timestamp,
                event.workflow_id,
                event.step_id,
                event.task_id,
                event.agent_id,
                event.tool_call_id,
                event.request_id,
                '{"safe":"visible"}',
                event.severity,
                event.trace_id,
                event.redacted,
                "{}",
            )
        return (1,)


class _DuplicateConnection(_SqlShapeConnection):
    def __init__(self, existing_event: StorageEventRecord, existing_offset: int) -> None:
        super().__init__()
        self.existing_event = existing_event
        self.existing_offset = existing_offset

    def cursor(self) -> _DuplicateCursor:
        return _DuplicateCursor(self)


def test_identical_duplicate_returns_existing_committed_offset() -> None:
    existing = _event()
    connection = _DuplicateConnection(existing, existing_offset=3)
    store = PostgresEventStore(
        "postgresql://example",
        connection_factory=lambda: connection,
    )

    offset = store.append_event(_event())

    assert offset == 3
    assert connection.commits == 1


def test_different_duplicate_event_id_raises_identity_collision() -> None:
    existing = _event()
    connection = _DuplicateConnection(existing, existing_offset=3)
    store = PostgresEventStore(
        "postgresql://example",
        connection_factory=lambda: connection,
    )
    changed = StorageEventRecord(
        event_id=existing.event_id,
        run_id=existing.run_id,
        event_type=existing.event_type,
        timestamp=existing.timestamp,
        step_id=existing.step_id,
        payload={"safe": "changed"},
    )

    with pytest.raises(EventIdentityCollisionError):
        store.append_event(changed)

    assert connection.commits == 0


@pytest.mark.parametrize(
    "time_fields",
    [{}, {"timestamp": ""}],
    ids=["missing", "blank"],
)
def test_storage_event_record_history_without_occurrence_time_fails_closed(
    time_fields: dict[str, str],
) -> None:
    payload = {
        "event_id": "event-missing-storage-time",
        "run_id": "run-missing-storage-time",
        "event_type": "workflow_started",
        "payload": {},
        **time_fields,
    }

    with pytest.raises((KeyError, ValueError)):
        StorageEventRecord.from_dict(payload)
