from __future__ import annotations

from typing import Any, Callable

import psycopg

from storage.metrics.models import StorageMetrics


ConnectionFactory = Callable[[], Any]


class PostgresStorageMetricsCollector:
    def __init__(self, dsn: str, *, connection_factory: ConnectionFactory | None = None) -> None:
        self.dsn = dsn
        self._connection_factory = connection_factory or (lambda: psycopg.connect(dsn))

    def collect(self) -> StorageMetrics:
        sql = """
        SELECT
            (SELECT COUNT(*) FROM workflow_runs) AS runs_count,
            (SELECT COUNT(*) FROM reports) AS reports_count,
            (SELECT COUNT(*) FROM artifact_index) AS artifacts_count,
            COALESCE((SELECT SUM(COALESCE(size_bytes, 0)) FROM artifact_index), 0)
                AS artifact_bytes_total,
            (SELECT COUNT(*) FROM workflow_events) AS events_count,
            (SELECT COUNT(*) FROM lineage_refs) AS lineage_refs_count
        """
        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, ())
                row = cursor.fetchone()
        row = row or (0, 0, 0, 0, 0, 0)
        return StorageMetrics(
            runs_count=int(row[0] or 0),
            reports_count=int(row[1] or 0),
            artifacts_count=int(row[2] or 0),
            artifact_bytes_total=int(row[3] or 0),
            events_count=int(row[4] or 0),
            lineage_refs_count=int(row[5] or 0),
            metadata={"source": "postgres"},
        )
