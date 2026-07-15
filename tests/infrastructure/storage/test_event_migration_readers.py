from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from framework.events.migration import MigrationSourceKind
from infrastructure.storage.events.migration_readers import (
    MigrationSourceReadError,
    PostgresEventMigrationReader,
    fingerprint_source_paths,
    iter_checkpoint_records,
    iter_jsonl_records,
)


def test_jsonl_and_checkpoint_readers_are_byte_for_byte_read_only(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    events_path.write_text(
        '{"event_id":"evt-1","event_type":"workflow_started",'
        '"occurred_at":"2026-07-15T01:00:00Z","run_id":"run-1",'
        '"payload":{"run_id":"run-1"},'
        '"schema_version":"newsroom.event_record.v1"}\n'
        '["not-an-object"]\n'
        '{"broken":\n',
        encoding="utf-8",
    )
    checkpoint_path = tmp_path / "checkpoint.json"
    checkpoint_path.write_text(
        '{"checkpoint_id":"cp-1","run_id":"run-1","event_offset":0}',
        encoding="utf-8",
    )
    before = {
        events_path: events_path.read_bytes(),
        checkpoint_path: checkpoint_path.read_bytes(),
    }

    events = list(
        iter_jsonl_records(
            [events_path],
            source_kind=MigrationSourceKind.LEGACY_RUN_JSONL,
        )
    )
    checkpoints = list(iter_checkpoint_records([checkpoint_path]))

    assert [record.issue_reason for record in events] == [
        None,
        "invalid_record_type",
        "invalid_json",
    ]
    assert len(checkpoints) == 1
    assert {path: path.read_bytes() for path in before} == before


def test_postgres_reader_sets_read_only_and_rolls_back_without_commit() -> None:
    workflow_row = (
        0,
        "evt-postgres-1",
        "run-1",
        "workflow_started",
        datetime(2026, 7, 15, 1, 0, tzinfo=UTC),
        None,
        None,
        None,
        None,
        None,
        None,
        {"run_id": "run-1"},
        "info",
        None,
        True,
        {},
    )
    connection = _FakeConnection(workflow_row)
    reader = PostgresEventMigrationReader(
        "postgresql://user:dsn-secret@localhost/newsroom",
        connection_factory=lambda: connection,
        batch_size=1,
    )

    records = list(reader.iter_records())

    assert len(records) == 1
    assert records[0].source_kind is MigrationSourceKind.POSTGRESQL_ROW
    assert connection.executed[0][0] == (
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
    )
    assert connection.rollback_count == 1
    assert connection.commit_count == 0
    assert connection.closed is True


def test_postgres_reader_does_not_invent_timezone_for_naive_timestamp() -> None:
    workflow_row = (
        0,
        "evt-postgres-naive",
        "run-1",
        "workflow_started",
        datetime(2026, 7, 15, 1, 0),
        None,
        None,
        None,
        None,
        None,
        None,
        {"run_id": "run-1"},
        "info",
        None,
        True,
        {},
    )
    connection = _FakeConnection(workflow_row)

    record = next(
        PostgresEventMigrationReader(
            "postgresql://localhost/newsroom",
            connection_factory=lambda: connection,
        ).iter_records()
    )

    assert record.value["timestamp"] == "2026-07-15T01:00:00"


def test_jsonl_reader_quarantines_invalid_utf8_per_line_and_continues(
    tmp_path: Path,
) -> None:
    path = tmp_path / "events.jsonl"
    valid = (
        b'{"event_id":"evt-1","event_type":"workflow_started",'
        b'"occurred_at":"2026-07-15T01:00:00Z","run_id":"run-1",'
        b'"payload":{"run_id":"run-1"}}\n'
    )
    path.write_bytes(valid + b'{"bad":"\xff"}\n' + valid.replace(b"evt-1", b"evt-2"))

    records = list(
        iter_jsonl_records(
            [path],
            source_kind=MigrationSourceKind.LEGACY_RUN_JSONL,
        )
    )

    assert [record.issue_reason for record in records] == [None, "invalid_utf8", None]


def test_fingerprint_errors_preserve_the_actual_source_kind(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"

    with pytest.raises(MigrationSourceReadError) as error:
        fingerprint_source_paths(
            [missing],
            suffix=".json",
            source_kind=MigrationSourceKind.CHECKPOINT,
        )

    assert error.value.source_kind is MigrationSourceKind.CHECKPOINT


def test_explicit_source_file_with_wrong_extension_fails_safely(tmp_path: Path) -> None:
    wrong_file = tmp_path / "events.json"
    wrong_file.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="file extension does not match source type"):
        fingerprint_source_paths(
            [wrong_file],
            suffix=".jsonl",
            source_kind=MigrationSourceKind.LEGACY_RUN_JSONL,
        )
    with pytest.raises(ValueError, match="file extension does not match source type"):
        list(
            iter_jsonl_records(
                [wrong_file],
                source_kind=MigrationSourceKind.LEGACY_RUN_JSONL,
            )
        )


def test_source_directory_filters_nonmatching_extensions(tmp_path: Path) -> None:
    (tmp_path / "ignored.json").write_text("{}", encoding="utf-8")

    assert fingerprint_source_paths(
        [tmp_path],
        suffix=".jsonl",
        source_kind=MigrationSourceKind.LEGACY_RUN_JSONL,
    ) == {}
    assert list(
        iter_jsonl_records(
            [tmp_path],
            source_kind=MigrationSourceKind.LEGACY_RUN_JSONL,
        )
    ) == []


class _FakeConnection:
    def __init__(self, workflow_row: tuple) -> None:
        self.workflow_row = workflow_row
        self.executed: list[tuple[str, object]] = []
        self.rollback_count = 0
        self.commit_count = 0
        self.closed = False

    def cursor(self):
        return _FakeCursor(self)

    def rollback(self) -> None:
        self.rollback_count += 1

    def commit(self) -> None:
        self.commit_count += 1

    def close(self) -> None:
        self.closed = True


class _FakeCursor:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection
        self.rows: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def execute(self, sql: str, params=None):
        normalized = " ".join(sql.split())
        self.connection.executed.append((normalized, params))
        if "information_schema.tables" in normalized:
            self.rows = [("workflow_events",)]
        elif "FROM workflow_events" in normalized:
            self.rows = [self.connection.workflow_row]
        else:
            self.rows = []
        return self

    def fetchall(self):
        rows = list(self.rows)
        self.rows = []
        return rows

    def fetchmany(self, size: int):
        rows = self.rows[:size]
        self.rows = self.rows[size:]
        return rows
