from datetime import UTC, datetime

import pytest

from business.foundation.models.source import SourceError, SourceHealth, SourceHealthStatus
from infrastructure.storage.postgres import PostgresRepository
from infrastructure.storage.records import ClaimRecord, EvidenceItemRecord, QualityResultRecord, SourceItemRecord
from infrastructure.storage.repository import ReportRecord, RunPersistenceBatch, WorkflowRunRecord


RESEARCH_WORKFLOW_ID = "research-paper-analysis"


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


def test_postgres_repository_saves_source_evidence_claim_and_quality_records() -> None:
    connection = FakeConnection()
    repository = PostgresRepository("postgresql://example", connection_factory=lambda: connection)

    repository.save_source_item(
        SourceItemRecord(
            source_item_id="raw-1",
            run_id="run-1",
            source_id="source",
            title="Title",
            url="https://example.com/a",
            canonical_url="https://example.com/canonical",
            published_at=datetime(2026, 5, 11, 1, 0, tzinfo=UTC),
            fetched_at=datetime(2026, 5, 11, 1, 5, tzinfo=UTC),
            raw_artifact_id="artifact-raw-1",
            metadata={"topic": "ai"},
        )
    )
    repository.save_evidence_item(
        EvidenceItemRecord(
            evidence_id="ev-1",
            run_id="run-1",
            claim="Title",
            summary="Summary",
            source_urls=["https://example.com/a"],
            source_item_ids=["raw-1"],
            confidence=0.9,
            category="policy",
            published_at=datetime(2026, 5, 11, 1, 0, tzinfo=UTC),
            lineage_json={"source_item_id": "raw-1"},
            metadata={"topic": "ai"},
        )
    )
    repository.save_claim(
        ClaimRecord(
            claim_id="claim-1",
            run_id="run-1",
            status="accepted",
            text="Title",
            confidence=0.8,
            supporting_evidence_ids=["ev-1"],
            supporting_sources=["https://example.com/a"],
        )
    )
    repository.save_quality_result(
        QualityResultRecord(
            quality_result_id="run-1:quality",
            run_id="run-1",
            decision="pass",
            passed=True,
            quality_score=1.0,
            citation_coverage_score=1.0,
            claim_support_score=1.0,
            evidence_alignment_score=1.0,
        )
    )

    assert "INSERT INTO source_items" in connection.calls[0][0]
    assert "canonical_url" in connection.calls[0][0]
    assert "metadata_json" in connection.calls[0][0]
    assert connection.calls[0][1][0] == "raw-1"
    assert connection.calls[0][1][5] == "https://example.com/canonical"
    assert connection.calls[0][1][8] == "artifact-raw-1"
    assert connection.calls[0][1][10] == '{"topic": "ai"}'
    assert "INSERT INTO evidence_items" in connection.calls[1][0]
    assert "source_urls" in connection.calls[1][0]
    assert "lineage_json" in connection.calls[1][0]
    assert connection.calls[1][1][0] == "ev-1"
    assert connection.calls[1][1][2] == "https://example.com/a"
    assert connection.calls[1][1][3] == '["https://example.com/a"]'
    assert connection.calls[1][1][4] == '["raw-1"]'
    assert connection.calls[1][1][8] == "policy"
    assert connection.calls[1][1][10] == '{"source_item_id": "raw-1"}'
    assert connection.calls[1][1][12] == '{"topic": "ai"}'
    assert "INSERT INTO claims" in connection.calls[2][0]
    assert "updated_at = now()" in connection.calls[2][0]
    assert connection.calls[2][1][2] == "accepted"
    assert "DELETE FROM claim_supports" in connection.calls[3][0]
    assert "INSERT INTO claim_supports" in connection.calls[4][0]
    assert connection.calls[4][1][0] == "claim-1:supporting:ev-1"
    assert connection.calls[4][1][3] == "ev-1"
    assert connection.calls[4][1][5] == 0.8
    assert "INSERT INTO quality_results" in connection.calls[5][0]
    assert "updated_at = now()" in connection.calls[5][0]
    assert connection.calls[5][1][0] == "run-1:quality"
    assert connection.calls[5][1][6] == 1.0


def test_postgres_repository_saves_run_records_in_one_transaction() -> None:
    connection = FakeConnection()
    repository = PostgresRepository("postgresql://example", connection_factory=lambda: connection)

    repository.save_run_records(
        RunPersistenceBatch(
            workflow_run=WorkflowRunRecord(
                run_id="run-1",
                workflow_id="daily",
                workflow_version="1",
                status="succeeded",
                profile="live-offline",
            ),
            report=ReportRecord(
                report_id="run-1:final",
                run_id="run-1",
                status="final",
                title="Daily",
            ),
            source_items=[
                SourceItemRecord(
                    source_item_id="raw-1",
                    run_id="run-1",
                    source_id="source",
                    title="Title",
                    url="https://example.com/a",
                )
            ],
            evidence_items=[
                EvidenceItemRecord(
                    evidence_id="ev-1",
                    run_id="run-1",
                    claim="Title",
                    summary="Summary",
                    source_urls=["https://example.com/a"],
                    source_item_ids=["raw-1"],
                    confidence=0.9,
                )
            ],
            claims=[
                ClaimRecord(
                    claim_id="claim-1",
                    run_id="run-1",
                    status="accepted",
                    text="Title",
                    supporting_evidence_ids=["ev-1"],
                )
            ],
            quality_result=QualityResultRecord(
                quality_result_id="run-1:quality",
                run_id="run-1",
                decision="pass",
                passed=True,
            ),
        )
    )

    executed_sql = "\n".join(sql for sql, _ in connection.calls)
    assert connection.commits == 1
    assert "INSERT INTO workflow_runs" in executed_sql
    assert "INSERT INTO reports" in executed_sql
    assert "INSERT INTO source_items" in executed_sql
    assert "INSERT INTO evidence_items" in executed_sql
    assert "INSERT INTO claims" in executed_sql
    assert "INSERT INTO claim_supports" in executed_sql
    assert "INSERT INTO quality_results" in executed_sql


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
    assert health.status == SourceHealthStatus.DOWN
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
                RESEARCH_WORKFLOW_ID,
            )
        ]
    )
    repository = PostgresRepository("postgresql://example", connection_factory=lambda: connection)

    records = repository.list_reports(limit=5, workflow_id=RESEARCH_WORKFLOW_ID)

    sql, params = connection.calls[0]
    assert "LEFT JOIN workflow_runs" in sql
    assert "wr.workflow_id = %s" in sql
    assert params == (RESEARCH_WORKFLOW_ID, 5)
    assert records[0].report_id == "report-1"
    assert records[0].workflow_id == RESEARCH_WORKFLOW_ID


def test_postgres_repository_lists_final_state_records_by_run() -> None:
    connection = FakeConnection(rows=[({"source_item_id": "raw-1"},), ('{"source_item_id":"raw-2"}',)])
    repository = PostgresRepository("postgresql://example", connection_factory=lambda: connection)

    records = repository.list_source_items("run-1")

    sql, params = connection.calls[0]
    assert "FROM source_items" in sql
    assert "WHERE run_id = %s" in sql
    assert "ORDER BY published_at ASC NULLS LAST, source_item_id ASC" in sql
    assert params == ("run-1",)
    assert records == [{"source_item_id": "raw-1"}, {"source_item_id": "raw-2"}]


@pytest.mark.parametrize(
    ("method_name", "table_name", "order_by", "expected"),
    [
        (
            "list_evidence_items",
            "evidence_items",
            "ORDER BY published_at ASC NULLS LAST, evidence_id ASC",
            {"evidence_id": "ev-1"},
        ),
        (
            "list_claims",
            "claims",
            "ORDER BY created_at ASC, claim_id ASC",
            {"claim_id": "claim-1"},
        ),
        (
            "list_quality_results",
            "quality_results",
            "ORDER BY created_at ASC, quality_result_id ASC",
            {"quality_result_id": "quality-1"},
        ),
    ],
)
def test_postgres_repository_lists_other_final_state_records_by_run(
    method_name,
    table_name,
    order_by,
    expected,
) -> None:
    connection = FakeConnection(rows=[(expected,)])
    repository = PostgresRepository("postgresql://example", connection_factory=lambda: connection)

    records = getattr(repository, method_name)("run-1")

    sql, params = connection.calls[0]
    assert f"FROM {table_name}" in sql
    assert "WHERE run_id = %s" in sql
    assert order_by in sql
    assert params == ("run-1",)
    assert records == [expected]
