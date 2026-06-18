import asyncio
from datetime import UTC, datetime

import pytest

from infrastructure.storage.events import EventRecord
from infrastructure.storage.postgres import PostgresEventStore


class FakeCursor:
    def __init__(self, calls, rows):
        self.calls = calls
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class FakeConnection:
    def __init__(self, rows=None):
        self.calls = []
        self.commits = 0
        self.rows = rows or []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return FakeCursor(self.calls, self.rows)

    def commit(self):
        self.commits += 1


def test_postgres_event_store_appends_event_with_run_offset() -> None:
    connection = FakeConnection(rows=[(2,)])
    store = PostgresEventStore("postgresql://example", connection_factory=lambda: connection)

    offset = store.append_event(
        EventRecord(
            event_id="event-1",
            run_id="run-1",
            event_type="step_succeeded",
            timestamp=datetime(2026, 5, 11, 1, 0, tzinfo=UTC),
            workflow_id="daily",
            step_id="collect",
            payload={"safe": "visible"},
            metadata={"workflow_version": "1"},
        )
    )

    assert offset == 2
    assert "SELECT COUNT(*) FROM workflow_events" in connection.calls[0][0]
    insert_sql, insert_params = connection.calls[1]
    assert "INSERT INTO workflow_events" in insert_sql
    assert insert_params[0] == "event-1"
    assert insert_params[2] == 2
    assert insert_params[14] == '{"safe": "visible"}'
    assert connection.commits == 1


def test_postgres_event_store_lists_events_by_run_and_step() -> None:
    row = _event_row(step_id="collect")
    connection = FakeConnection(rows=[row])
    store = PostgresEventStore("postgresql://example", connection_factory=lambda: connection)

    run_events = store.list_by_run("run-1", limit=10)
    step_events = store.list_by_step("run-1", "collect")
    type_events = store.filter_by_type("run-1", "workflow_succeeded", limit=5)

    assert run_events[0].event_id == "event-1"
    assert run_events[0].payload == {"status": "ok"}
    assert run_events[0].timestamp == datetime(2026, 5, 11, 1, 0, tzinfo=UTC)
    assert step_events[0].step_id == "collect"
    assert type_events[0].event_type == "workflow_succeeded"
    assert "LIMIT %s" in connection.calls[0][0]
    assert connection.calls[0][1] == ("run-1", 10)
    assert "step_id = %s" in connection.calls[1][0]
    assert "event_type = %s" in connection.calls[2][0]
    assert connection.calls[2][1] == ("run-1", "workflow_succeeded", 5)


def test_postgres_event_store_streams_from_offset() -> None:
    connection = FakeConnection(rows=[_event_row(step_id=None)])
    store = PostgresEventStore("postgresql://example", connection_factory=lambda: connection)

    async def collect():
        return [event async for event in store.stream_from_offset("run-1", 3)]

    events = asyncio.run(collect())

    assert events[0].event_type == "workflow_succeeded"
    assert "event_offset >= %s" in connection.calls[0][0]
    assert connection.calls[0][1] == ("run-1", 3)


def test_postgres_event_store_rejects_invalid_limit() -> None:
    store = PostgresEventStore("postgresql://example", connection_factory=lambda: FakeConnection())

    with pytest.raises(ValueError, match="limit must be greater than zero"):
        store.list_by_run("run-1", limit=0)

    with pytest.raises(ValueError, match="limit must be greater than zero"):
        store.filter_by_type("run-1", "workflow_succeeded", limit=0)

    with pytest.raises(ValueError, match="event_type is required"):
        store.filter_by_type("run-1", "")


def _event_row(step_id):
    return (
        "event-1",
        "run-1",
        "workflow_succeeded",
        "2026-05-11T01:00:00Z",
        "daily",
        step_id,
        None,
        None,
        None,
        None,
        '{"status": "ok"}',
        "info",
        None,
        True,
        '{"workflow_version": "1"}',
    )
