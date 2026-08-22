from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256

import pytest

from framework.agent.artifacts.models import (
    ArtifactRef,
    ArtifactWriteRequest,
    artifact_identity_key,
    canonical_artifact_relative_path,
)
from framework.agent.artifacts.stores.errors import ArtifactStoreMetadataError
from framework.shared.graph_identity import GraphRunIdentity, GraphStageIdentity
from infrastructure.storage.artifacts import ArtifactIndexNotFoundError
from infrastructure.storage.postgres import PostgresArtifactIndexStore


_GRAPH_CHECKSUM = f"sha256:{'a' * 64}"


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


def test_postgres_artifact_index_inserts_immutable_artifact_ref() -> None:
    connection = FakeConnection()
    store = _store(connection)
    ref = _ref("artifact-1")

    store.index_artifact(ref)

    assert "pg_advisory_xact_lock" in connection.calls[0][0]
    assert connection.calls[0][1] == (artifact_identity_key(ref),)
    assert "FOR UPDATE" in connection.calls[1][0]
    sql, params = connection.calls[2]
    assert "INSERT INTO artifact_index" in sql
    assert "ON CONFLICT" not in sql
    assert params[:4] == (
        "artifact-1",
        "run-1",
        "standalone",
        artifact_identity_key(ref),
    )
    assert params[11] == '{"source": "test"}'
    assert connection.commits == 1


def test_postgres_artifact_index_exact_duplicate_is_idempotent() -> None:
    ref = _graph_ref("artifact-1", node_instance_id="reader:1", attempt=2)
    connection = FakeConnection(rows=[_row(ref)])
    store = _store(connection)

    store.index_artifact(ref)

    assert len(connection.calls) == 2
    assert connection.commits == 1


def test_postgres_artifact_index_rejects_conflicting_duplicate() -> None:
    ref = _graph_ref("artifact-1", node_instance_id="reader:1", attempt=2)
    connection = FakeConnection(rows=[_row(ref)])
    store = _store(connection)

    with pytest.raises(ArtifactStoreMetadataError, match="identity conflict"):
        store.index_artifact(replace(ref, checksum=sha256(b"changed").hexdigest()))


def test_postgres_artifact_index_gets_and_lists_standalone_refs() -> None:
    ref = _ref("artifact-1")
    connection = FakeConnection(rows=[_row(ref)])
    store = _store(connection)

    found = store.get_artifact(ref)
    run_refs = store.list_by_run("run-1")
    all_refs = store.list_all()
    type_refs = store.list_by_type("report_json", run_id="run-1")

    assert found == ref
    assert run_refs == [ref]
    assert all_refs == [ref]
    assert type_refs == [ref]
    assert "artifact_identity_key = %s" in connection.calls[0][0]
    assert connection.calls[0][1] == (artifact_identity_key(ref),)
    assert "WHERE run_id = %s" in connection.calls[1][0]
    assert "WHERE artifact_type = %s AND run_id = %s" in connection.calls[3][0]


def test_postgres_artifact_index_raises_when_exact_ref_is_missing() -> None:
    connection = FakeConnection()
    store = _store(connection)

    with pytest.raises(ArtifactIndexNotFoundError, match="artifact index record not found"):
        store.get_artifact(_ref("missing"))

    with pytest.raises(ValueError, match="artifact_type is required"):
        store.list_by_type("")


def test_postgres_artifact_index_deletes_by_exact_identity() -> None:
    ref = _graph_ref("artifact-1", node_instance_id="reader:1", attempt=2)
    connection = FakeConnection(rows=[_row(ref)])
    store = _store(connection)

    store.delete_artifact(ref)

    assert "FOR UPDATE" in connection.calls[0][0]
    assert connection.calls[0][1] == (artifact_identity_key(ref),)
    assert "DELETE FROM artifact_index WHERE artifact_identity_key = %s" in connection.calls[1][0]
    assert connection.calls[1][1] == (artifact_identity_key(ref),)
    assert connection.commits == 1


def test_postgres_artifact_index_delete_rejects_tampered_ref() -> None:
    ref = _graph_ref("artifact-1", node_instance_id="reader:1", attempt=2)
    connection = FakeConnection(rows=[_row(ref)])
    store = _store(connection)

    with pytest.raises(ArtifactStoreMetadataError, match="identity mismatch"):
        store.delete_artifact(replace(ref, metadata={"tampered": True}))

    assert len(connection.calls) == 1
    assert connection.commits == 0


def test_postgres_artifact_index_roundtrips_graph_lineage_and_exact_queries() -> None:
    ref = _graph_ref("artifact-graph-1", node_instance_id="reader:1", attempt=2)
    connection = FakeConnection(rows=[_row(ref)])
    store = _store(connection)

    found = store.get_artifact(ref)
    node_refs = store.list_by_node_instance(
        _stage_identity("reader:1"),
        activity_id="activity-1",
        attempt=2,
    )
    graph_refs = store.list_by_graph(_run_identity())

    assert found == ref
    assert node_refs == [ref]
    assert graph_refs == [ref]
    node_sql, node_params = connection.calls[1]
    assert "graph_checksum = %s" in node_sql
    assert "node_instance_id = %s" in node_sql
    assert "activity_id = %s AND attempt = %s" in node_sql
    assert node_params == (
        "run-1",
        "research",
        "2.0.0",
        "research@2.0.0",
        _GRAPH_CHECKSUM,
        "reader",
        "reader:1",
        "activity-1",
        2,
    )
    assert connection.calls[2][1] == (
        "run-1",
        "research",
        "2.0.0",
        "research@2.0.0",
        _GRAPH_CHECKSUM,
    )


def test_postgres_artifact_index_same_artifact_id_has_distinct_physical_keys() -> None:
    left = _graph_ref("shared", node_instance_id="reader:1", attempt=1)
    retry = _graph_ref("shared", node_instance_id="reader:1", attempt=2)
    right = _graph_ref("shared", node_instance_id="reader:2", attempt=1)

    assert len({artifact_identity_key(left), artifact_identity_key(retry), artifact_identity_key(right)}) == 3


def test_postgres_artifact_index_requires_typed_exact_graph_queries() -> None:
    connection = FakeConnection()
    store = _store(connection)

    with pytest.raises(TypeError, match="GraphStageIdentity"):
        store.list_by_node_instance("run-1")
    with pytest.raises(TypeError, match="GraphRunIdentity"):
        store.list_by_graph("run-1")
    with pytest.raises(ValueError, match="provided together"):
        store.list_by_node_instance(_stage_identity("reader:1"), activity_id="activity-1")

    assert connection.calls == []


def test_postgres_artifact_index_rejects_pre_cutover_row_shape() -> None:
    connection = FakeConnection(rows=[_row(_ref("artifact-1"))[:11]])
    store = _store(connection)

    with pytest.raises(ArtifactStoreMetadataError, match="Graph-only schema"):
        store.list_by_run("run-1")


def _store(connection: FakeConnection) -> PostgresArtifactIndexStore:
    return PostgresArtifactIndexStore(
        "postgresql://example",
        connection_factory=lambda: connection,
    )


def _ref(artifact_id: str) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=artifact_id,
        run_id="run-1",
        scope_kind="standalone",
        artifact_type="report_json",
        path=f"artifacts/report/{artifact_id}.json",
        content_type="application/json",
        size_bytes=2,
        checksum=sha256(b"{}").hexdigest(),
        redacted=True,
        created_at=datetime(2026, 5, 11, 1, 0, tzinfo=UTC),
        metadata={"source": "test"},
    )


def _graph_ref(
    artifact_id: str,
    *,
    node_instance_id: str,
    attempt: int,
) -> ArtifactRef:
    request = ArtifactWriteRequest(
        artifact_id=artifact_id,
        run_id="run-1",
        scope_kind="graph",
        graph_id="research",
        graph_version="2.0.0",
        graph_ref="research@2.0.0",
        graph_checksum=_GRAPH_CHECKSUM,
        node_id="reader",
        node_instance_id=node_instance_id,
        graph_checkpoint_ref="checkpoint://run-1/1",
        activity_id="activity-1",
        attempt=attempt,
        artifact_type="report_json",
        content=b"{}",
        content_type="application/json",
    )
    return ArtifactRef(
        artifact_id=artifact_id,
        run_id=request.run_id,
        scope_kind=request.scope_kind,
        graph_id=request.graph_id,
        graph_version=request.graph_version,
        graph_ref=request.graph_ref,
        graph_checksum=request.graph_checksum,
        node_id=request.node_id,
        node_instance_id=request.node_instance_id,
        graph_checkpoint_ref=request.graph_checkpoint_ref,
        activity_id=request.activity_id,
        attempt=request.attempt,
        artifact_type=request.artifact_type,
        path=canonical_artifact_relative_path(request),
        content_type=request.content_type,
        size_bytes=2,
        checksum=sha256(b"{}").hexdigest(),
        redacted=True,
        created_at=datetime(2026, 5, 11, 1, attempt, tzinfo=UTC),
        metadata={"source": "graph-test"},
    )


def _stage_identity(node_instance_id: str) -> GraphStageIdentity:
    return GraphStageIdentity(
        **_run_identity().to_dict(),
        node_id="reader",
        node_instance_id=node_instance_id,
    )


def _run_identity() -> GraphRunIdentity:
    return GraphRunIdentity(
        run_id="run-1",
        graph_id="research",
        graph_version="2.0.0",
        graph_ref="research@2.0.0",
        graph_checksum=_GRAPH_CHECKSUM,
    )


def _row(ref: ArtifactRef) -> tuple[object, ...]:
    return (
        ref.artifact_id,
        ref.run_id,
        ref.scope_kind,
        ref.artifact_type,
        ref.path,
        ref.content_type,
        ref.size_bytes,
        ref.checksum,
        ref.redacted,
        "2026-05-11T01:00:00Z" if ref.scope_kind == "standalone" else ref.created_at,
        ref.metadata,
        ref.graph_id,
        ref.graph_version,
        ref.graph_ref,
        ref.graph_checksum,
        ref.node_id,
        ref.node_instance_id,
        ref.graph_checkpoint_ref,
        ref.activity_id,
        ref.attempt,
        artifact_identity_key(ref),
    )
