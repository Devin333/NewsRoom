from datetime import UTC, datetime

import pytest

from domain.sources import SourceError, SourceHealth, SourceHealthStatus
from storage.postgres import PostgresRepository
from storage.repository import ReportRecord, WorkflowRunRecord


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


def test_postgres_repository_runs_migrations() -> None:
    connection = FakeConnection()
    repository = PostgresRepository("postgresql://example", connection_factory=lambda: connection)

    repository.migrate()

    assert "CREATE TABLE IF NOT EXISTS workflow_runs" in connection.calls[0][0]
    assert "citation_coverage_score" in connection.calls[0][0]
    assert connection.commits == 1


def test_postgres_repository_saves_workflow_run() -> None:
    connection = FakeConnection()
    repository = PostgresRepository("postgresql://example", connection_factory=lambda: connection)

    repository.save_workflow_run(
        WorkflowRunRecord(
            run_id="run-1",
            workflow_id="daily",
            workflow_version="1",
            status="succeeded",
            profile="live-offline",
            metrics={"quality_score": 1.0},
        )
    )

    sql, params = connection.calls[0]
    assert "INSERT INTO workflow_runs" in sql
    assert params[0] == "run-1"
    assert params[9] == '{"quality_score": 1.0}'


def test_postgres_repository_saves_report() -> None:
    connection = FakeConnection()
    repository = PostgresRepository("postgresql://example", connection_factory=lambda: connection)

    repository.save_report(
        ReportRecord(
            report_id="report-1",
            run_id="run-1",
            status="final",
            title="Report",
            report_json={"title": "Report"},
            quality_score=0.9,
            citation_coverage_score=0.8,
        )
    )

    sql, params = connection.calls[0]
    assert "INSERT INTO reports" in sql
    assert params[0] == "report-1"
    assert params[4] == '{"title": "Report"}'
    assert params[7] == 0.8


def test_postgres_repository_updates_source_health() -> None:
    connection = FakeConnection()
    repository = PostgresRepository("postgresql://example", connection_factory=lambda: connection)

    repository.update_source_health(
        SourceHealth(
            source_id="rss-example",
            status="degraded",
            consecutive_failures=1,
            success_count_24h=2,
            failure_count_24h=1,
            avg_latency_ms_24h=123.5,
            last_error=SourceError(
                source_id="rss-example",
                error_type="fetch_timeout",
                error_message="timed out",
                url="https://example.com/feed.xml",
            ),
        )
    )

    sql, params = connection.calls[0]
    assert "INSERT INTO source_health" in sql
    assert "source_name" in sql
    assert "url" in sql
    assert "ON CONFLICT (source_id)" in sql
    assert params[0] == "rss-example"
    assert params[1] is None
    assert params[2] is None
    assert params[3] == "degraded"
    assert params[4] == 1
    assert '"error_type": "fetch_timeout"' in params[8]
    assert params[9] == 2
    assert params[10] == 1
    assert params[11] == 123.5


def test_postgres_repository_reads_source_health_by_id() -> None:
    connection = FakeConnection(
        rows=[
            (
                "rss-example",
                "Example RSS",
                "https://example.com/feed.xml",
                "cooling_down",
                3,
                datetime(2026, 5, 11, 1, 0, tzinfo=UTC),
                datetime(2026, 5, 11, 2, 0, tzinfo=UTC),
                datetime(2026, 5, 11, 2, 5, tzinfo=UTC),
                {
                    "source_id": "rss-example",
                    "source_name": "Example RSS",
                    "error_type": "fetch_timeout",
                    "error_message": "timed out",
                    "url": "https://example.com/feed.xml",
                    "retryable": True,
                    "occurred_at": "2026-05-11T02:00:00Z",
                    "metadata": {"phase": "fetch"},
                },
                4,
                2,
                250.5,
            )
        ]
    )
    repository = PostgresRepository("postgresql://example", connection_factory=lambda: connection)

    health = repository.get_source_health("rss-example")

    sql, params = connection.calls[0]
    assert "FROM source_health" in sql
    assert "WHERE source_id = %s" in sql
    assert params == ("rss-example",)
    assert health is not None
    assert health.source_id == "rss-example"
    assert health.source_name == "Example RSS"
    assert health.url == "https://example.com/feed.xml"
    assert health.status == SourceHealthStatus.COOLING_DOWN
    assert health.consecutive_failures == 3
    assert health.success_count_24h == 4
    assert health.failure_count_24h == 2
    assert health.avg_latency_ms_24h == 250.5
    assert health.last_error is not None
    assert health.last_error.error_type == "fetch_timeout"
    assert health.last_error.metadata == {"phase": "fetch"}


def test_postgres_repository_lists_source_health_with_status_filter() -> None:
    connection = FakeConnection(
        rows=[
            (
                "rss-example",
                "Example RSS",
                "https://example.com/feed.xml",
                "degraded",
                1,
                None,
                None,
                None,
                None,
                0,
                1,
                None,
            )
        ]
    )
    repository = PostgresRepository("postgresql://example", connection_factory=lambda: connection)

    records = repository.list_source_health(status="degraded")

    sql, params = connection.calls[0]
    assert "WHERE status = %s" in sql
    assert "ORDER BY source_id" in sql
    assert params == ("degraded",)
    assert records[0].source_id == "rss-example"
    assert records[0].status == SourceHealthStatus.DEGRADED


def test_postgres_repository_reads_latest_report() -> None:
    connection = FakeConnection(
        rows=[
            (
                "report-1",
                "run-1",
                "final",
                "AI Report",
                {"title": "AI Report"},
                "# AI Report",
                0.9,
                0.8,
                ".newsroom/runs/run-1/manifest.json",
                datetime(2026, 5, 11, 1, 0, tzinfo=UTC),
            )
        ]
    )
    repository = PostgresRepository("postgresql://example", connection_factory=lambda: connection)

    record = repository.latest_report()

    sql, params = connection.calls[0]
    assert "FROM reports r" in sql
    assert "ORDER BY r.updated_at DESC" in sql
    assert params == ()
    assert record.report_id == "report-1"
    assert record.run_id == "run-1"
    assert record.title == "AI Report"
    assert record.report_json == {"title": "AI Report"}
    assert record.report_markdown == "# AI Report"
    assert record.citation_coverage_score == 0.8
    assert record.finished_at == "2026-05-11T01:00:00Z"


def test_postgres_repository_gets_report_by_id() -> None:
    connection = FakeConnection(
        rows=[
            (
                "report-1",
                "run-1",
                "final",
                "AI Report",
                '{"title": "AI Report"}',
                "# AI Report",
                0.9,
                0.8,
                ".newsroom/runs/run-1/manifest.json",
                "2026-05-11T01:00:00Z",
            )
        ]
    )
    repository = PostgresRepository("postgresql://example", connection_factory=lambda: connection)

    record = repository.get_report("report-1")

    sql, params = connection.calls[0]
    assert "WHERE r.report_id = %s" in sql
    assert params == ("report-1",)
    assert record.report_id == "report-1"
    assert record.report_json == {"title": "AI Report"}
    assert record.citation_coverage_score == 0.8


def test_postgres_repository_raises_when_report_missing() -> None:
    connection = FakeConnection(rows=[])
    repository = PostgresRepository("postgresql://example", connection_factory=lambda: connection)

    with pytest.raises(FileNotFoundError, match="report not found"):
        repository.get_report("missing")


def test_postgres_repository_searches_reports() -> None:
    connection = FakeConnection(
        rows=[
            (
                "report-1",
                "run-1",
                "final",
                "AI Policy Report",
                0.9,
                0.8,
                ".newsroom/runs/run-1/manifest.json",
                "2026-05-11T01:00:00Z",
            )
        ]
    )
    repository = PostgresRepository("postgresql://example", connection_factory=lambda: connection)

    records = repository.search_reports("policy", limit=5)

    sql, params = connection.calls[0]
    assert "ILIKE" in sql
    assert params == ("%policy%", "%policy%", "%policy%", 5)
    assert records[0].report_id == "report-1"
    assert records[0].title == "AI Policy Report"
    assert records[0].citation_coverage_score == 0.8


def test_postgres_repository_lists_reports_with_workflow_filter() -> None:
    connection = FakeConnection(
        rows=[
            (
                "report-1",
                "run-1",
                "final",
                "AI Policy Report",
                0.9,
                0.8,
                ".newsroom/runs/run-1/manifest.json",
                "2026-05-11T01:00:00Z",
                "daily-intelligence-live",
            )
        ]
    )
    repository = PostgresRepository("postgresql://example", connection_factory=lambda: connection)

    records = repository.list_reports(limit=5, workflow_id="daily-intelligence-live")

    sql, params = connection.calls[0]
    assert "LEFT JOIN workflow_runs" in sql
    assert "wr.workflow_id = %s" in sql
    assert params == ("daily-intelligence-live", 5)
    assert records[0].report_id == "report-1"
    assert records[0].workflow_id == "daily-intelligence-live"
