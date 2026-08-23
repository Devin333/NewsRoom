from datetime import UTC, datetime

from infrastructure.storage.lineage import LineageRef
from infrastructure.storage.postgres import PostgresLineageStore
from framework.shared.graph_identity import GraphRunIdentity


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


def test_postgres_lineage_store_upserts_ref() -> None:
    connection = FakeConnection()
    store = PostgresLineageStore("postgresql://example", connection_factory=lambda: connection)
    ref = _ref()

    store.record(ref)

    sql, params = connection.calls[0]
    assert "INSERT INTO lineage_refs" in sql
    assert "ON CONFLICT (lineage_id)" in sql
    assert params[0] == ref.lineage_id
    assert params[1] == "run-1"
    assert params[8] == '{"source": "test"}'
    assert connection.commits == 1
    assert "graph_identity" in sql


def test_postgres_lineage_store_round_trips_graph_identity() -> None:
    identity = GraphRunIdentity(
        run_id="run-1",
        graph_id="research.paper-analysis",
        graph_version="v2",
        graph_ref="research.paper-analysis@v2",
        graph_checksum="sha256:" + "0" * 64,
    )
    connection = FakeConnection(rows=[_row(graph_identity=identity)])
    store = PostgresLineageStore("postgresql://example", connection_factory=lambda: connection)

    restored = store.list_by_run("run-1")

    assert restored[0].graph_identity == identity


def test_postgres_lineage_store_lists_upstream_and_downstream() -> None:
    connection = FakeConnection(rows=[_row()])
    store = PostgresLineageStore("postgresql://example", connection_factory=lambda: connection)

    listed = store.list_by_run("run-1")
    upstream = store.upstream("run-1", "evidence", "ev-1")
    downstream = store.downstream("run-1", "source_item", "raw-1")

    assert listed == [_ref()]
    assert upstream == [_ref()]
    assert downstream == [_ref()]
    assert "WHERE run_id = %s" in connection.calls[0][0]
    assert "target_type = %s" in connection.calls[1][0]
    assert "source_type = %s" in connection.calls[2][0]


def _ref() -> LineageRef:
    return LineageRef(
        lineage_id="lin-test",
        run_id="run-1",
        source_type="source_item",
        source_id="raw-1",
        target_type="evidence",
        target_id="ev-1",
        relation_type="source_to_evidence",
        created_at=datetime(2026, 5, 11, 1, 0, tzinfo=UTC),
        metadata={"source": "test"},
    )


def _row(*, graph_identity: GraphRunIdentity | None = None):
    ref = _ref()
    return (
        ref.lineage_id,
        ref.run_id,
        ref.source_type,
        ref.source_id,
        ref.target_type,
        ref.target_id,
        ref.relation_type,
        "2026-05-11T01:00:00Z",
        '{"source": "test"}',
        graph_identity.to_dict() if graph_identity else {},
    )
