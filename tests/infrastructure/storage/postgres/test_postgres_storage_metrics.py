from infrastructure.storage.postgres import PostgresStorageMetricsCollector


class FakeCursor:
    def __init__(self, calls, row):
        self.calls = calls
        self.row = row

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self, row):
        self.calls = []
        self.row = row

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return FakeCursor(self.calls, self.row)


def test_postgres_storage_metrics_collects_aggregate_counts() -> None:
    connection = FakeConnection(row=(2, 1, 4, 5, 6, 7, 8, 9, 128, 10, 3))
    collector = PostgresStorageMetricsCollector(
        "postgresql://example",
        connection_factory=lambda: connection,
    )

    metrics = collector.collect()

    assert metrics.runs_count == 2
    assert metrics.reports_count == 1
    assert metrics.artifacts_count == 4
    assert metrics.source_items_count == 5
    assert metrics.evidence_items_count == 6
    assert metrics.claims_count == 7
    assert metrics.quality_results_count == 8
    assert metrics.vector_documents_count == 9
    assert metrics.artifact_bytes_total == 128
    assert metrics.events_count == 10
    assert metrics.lineage_refs_count == 3
    assert metrics.metadata["source"] == "postgres"
    sql, params = connection.calls[0]
    assert "FROM workflow_runs" in sql
    assert "FROM artifact_index" in sql
    assert "FROM quality_results" in sql
    assert "FROM memory_documents" in sql
    assert "FROM workflow_events" in sql
    assert "FROM lineage_refs" in sql
    assert params == ()
