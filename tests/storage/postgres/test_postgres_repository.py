from storage.postgres import PostgresRepository
from storage.repository import ReportRecord, WorkflowRunRecord


class FakeCursor:
    def __init__(self, calls):
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))


class FakeConnection:
    def __init__(self):
        self.calls = []
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return FakeCursor(self.calls)

    def commit(self):
        self.commits += 1


def test_postgres_repository_runs_migrations() -> None:
    connection = FakeConnection()
    repository = PostgresRepository("postgresql://example", connection_factory=lambda: connection)

    repository.migrate()

    assert "CREATE TABLE IF NOT EXISTS workflow_runs" in connection.calls[0][0]
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
        )
    )

    sql, params = connection.calls[0]
    assert "INSERT INTO reports" in sql
    assert params[0] == "report-1"
    assert params[4] == '{"title": "Report"}'
