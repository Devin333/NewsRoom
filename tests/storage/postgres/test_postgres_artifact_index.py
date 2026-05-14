from datetime import UTC, datetime
from hashlib import sha256

import pytest

from storage.artifacts import ArtifactIndexNotFoundError, ArtifactRef
from storage.postgres import PostgresArtifactIndexStore


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


def test_postgres_artifact_index_upserts_artifact_ref() -> None:
    connection = FakeConnection()
    store = PostgresArtifactIndexStore("postgresql://example", connection_factory=lambda: connection)
    ref = _ref("artifact-1")

    store.index_artifact(ref)

    sql, params = connection.calls[0]
    assert "INSERT INTO artifact_index" in sql
    assert "ON CONFLICT (run_id, artifact_id)" in sql
    assert params[0] == "artifact-1"
    assert params[1] == "run-1"
    assert params[10] == '{"source": "test"}'
    assert connection.commits == 1


def test_postgres_artifact_index_gets_and_lists_refs() -> None:
    connection = FakeConnection(rows=[_row("artifact-1")])
    store = PostgresArtifactIndexStore("postgresql://example", connection_factory=lambda: connection)

    found = store.get_artifact("run-1", "artifact-1")
    run_refs = store.list_by_run("run-1")
    all_refs = store.list_all()
    step_refs = store.list_by_step("run-1", "draft")
    type_refs = store.list_by_type("report_json", run_id="run-1")

    assert found == _ref("artifact-1")
    assert run_refs == [found]
    assert all_refs == [found]
    assert step_refs == [found]
    assert type_refs == [found]
    assert "WHERE run_id = %s AND artifact_id = %s" in connection.calls[0][0]
    assert "WHERE run_id = %s" in connection.calls[1][0]
    assert "WHERE run_id = %s AND step_id = %s" in connection.calls[3][0]
    assert "WHERE artifact_type = %s AND run_id = %s" in connection.calls[4][0]
    assert connection.calls[4][1] == ("report_json", "run-1")


def test_postgres_artifact_index_lists_refs_by_type_across_runs() -> None:
    connection = FakeConnection(rows=[_row("artifact-1")])
    store = PostgresArtifactIndexStore("postgresql://example", connection_factory=lambda: connection)

    refs = store.list_by_type("report_json")

    assert refs == [_ref("artifact-1")]
    assert "WHERE artifact_type = %s" in connection.calls[0][0]
    assert connection.calls[0][1] == ("report_json",)


def test_postgres_artifact_index_raises_when_missing() -> None:
    connection = FakeConnection(rows=[])
    store = PostgresArtifactIndexStore("postgresql://example", connection_factory=lambda: connection)

    with pytest.raises(ArtifactIndexNotFoundError, match="artifact index record not found"):
        store.get_artifact("run-1", "missing")

    with pytest.raises(ValueError, match="artifact_type is required"):
        store.list_by_type("")


def test_postgres_artifact_index_deletes_ref() -> None:
    connection = FakeConnection()
    store = PostgresArtifactIndexStore("postgresql://example", connection_factory=lambda: connection)

    store.delete_artifact("run-1", "artifact-1")

    assert "DELETE FROM artifact_index" in connection.calls[0][0]
    assert connection.calls[0][1] == ("run-1", "artifact-1")
    assert connection.commits == 1


def _ref(artifact_id: str) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=artifact_id,
        run_id="run-1",
        step_id="draft",
        artifact_type="report_json",
        path=f"artifacts/report/{artifact_id}.json",
        content_type="application/json",
        size_bytes=2,
        checksum=sha256(b"{}").hexdigest(),
        redacted=True,
        created_at=datetime(2026, 5, 11, 1, 0, tzinfo=UTC),
        metadata={"source": "test"},
    )


def _row(artifact_id: str):
    ref = _ref(artifact_id)
    return (
        ref.artifact_id,
        ref.run_id,
        ref.step_id,
        ref.artifact_type,
        ref.path,
        ref.content_type,
        ref.size_bytes,
        ref.checksum,
        ref.redacted,
        "2026-05-11T01:00:00Z",
        '{"source": "test"}',
    )
