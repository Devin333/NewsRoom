from __future__ import annotations

from business.research.domain import ReaderIssue
from business.research.domain.reader_repair import ReaderRepairStrategy
from infrastructure.storage.postgres import PostgresReaderRepairMemoryRepository
from tests.business.research.reader_repair._fixtures import make_repair_case


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.connection.calls.append((sql, params))

    def fetchone(self):
        if self.connection.fetchone_rows:
            return self.connection.fetchone_rows.pop(0)
        return None

    def fetchall(self):
        if self.connection.fetchall_rows:
            return list(self.connection.fetchall_rows.pop(0))
        return []


class FakeConnection:
    def __init__(self, *, fetchone_rows=None, fetchall_rows=None):
        self.calls = []
        self.commits = 0
        self.fetchone_rows = list(fetchone_rows or [])
        self.fetchall_rows = list(fetchall_rows or [])

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1


def test_postgres_reader_repair_memory_repository_writes_case_and_version() -> None:
    issue = _issue()
    case = make_repair_case("case-1", issue=issue, successful=True)
    connection = FakeConnection(fetchone_rows=[(1,)])
    repository = PostgresReaderRepairMemoryRepository(
        "postgresql://example",
        connection_factory=lambda: connection,
    )

    ref = repository.write_object(
        namespace="research.reader_repair",
        object_type="case",
        object_id=case.repair_case_id,
        issue_type=case.issue.issue_type,
        error_signature=case.issue.error_signature,
        successful=case.successful,
        status=None,
        memory_kind=case.memory_kind,
        payload=case.to_dict(),
    )

    executed_sql = "\n".join(sql for sql, _ in connection.calls)
    assert ref == "memory://research.reader_repair/case/case-1"
    assert "INSERT INTO reader_repair_memory_objects" in executed_sql
    assert "INSERT INTO reader_repair_memory_versions" in executed_sql
    assert connection.calls[-1][1][4] == "upsert"
    assert connection.commits == 1


def test_postgres_reader_repair_memory_repository_recalls_cases_and_strategies() -> None:
    issue = _issue()
    case = make_repair_case("case-1", issue=issue, successful=True)
    strategy = ReaderRepairStrategy(
        strategy_id="strategy-1",
        issue_type="table_parse_error",
        applicability="Repeated table parse repair.",
        steps=["match table signature", "restore cells", "verify lineage"],
        confidence=0.9,
        source_case_refs=["case-1"],
        status="promoted_memory",
    )
    connection = FakeConnection(fetchall_rows=[
        [(case.to_dict(),)],
        [(strategy.to_dict(),)],
    ])
    repository = PostgresReaderRepairMemoryRepository(
        "postgresql://example",
        connection_factory=lambda: connection,
    )

    cases = repository.recall_case_payloads(
        namespace="research.reader_repair",
        memory_kinds=["episodic", "procedural"],
        issue_type=issue.issue_type,
        error_signature=issue.error_signature,
    )
    strategies = repository.recall_strategy_payloads(
        namespace="research.reader_repair",
        issue_type="table_parse_error",
        statuses=("promoted_memory", "skill_candidate_ready", "validated"),
    )

    assert cases[0]["repair_case_id"] == "case-1"
    assert strategies[0]["strategy_id"] == "strategy-1"
    executed_sql = "\n".join(sql for sql, _ in connection.calls)
    assert "memory_kind = ANY" in executed_sql
    assert "status IN" in executed_sql


def test_postgres_reader_repair_memory_repository_lists_and_rolls_back_case_versions() -> None:
    issue = _issue()
    case = make_repair_case("case-1", issue=issue, successful=True)
    connection = FakeConnection(
        fetchone_rows=[(case.to_dict(),), (2,)],
        fetchall_rows=[[(1, "upsert", case.to_dict(), "2026-07-03T00:00:00Z")]],
    )
    repository = PostgresReaderRepairMemoryRepository(
        "postgresql://example",
        connection_factory=lambda: connection,
    )

    versions = repository.list_versions(
        namespace="research.reader_repair",
        object_type="case",
        object_id="case-1",
    )
    payload = repository.version_payload(
        namespace="research.reader_repair",
        object_type="case",
        object_id="case-1",
        version=1,
    )
    ref = repository.write_object(
        namespace="research.reader_repair",
        object_type="case",
        object_id="case-1",
        issue_type=payload["issue"]["issue_type"],
        error_signature=payload["issue"]["error_signature"],
        successful=payload["successful"],
        status=None,
        memory_kind=payload["memory_kind"],
        payload=payload,
        operation="rollback",
    )

    assert versions[0].version == 1
    assert versions[0].operation == "upsert"
    assert ref == "memory://research.reader_repair/case/case-1"
    assert connection.calls[-1][1][4] == "rollback"
    assert connection.commits == 1


def test_postgres_reader_repair_memory_repository_rolls_back_strategy_versions() -> None:
    strategy = ReaderRepairStrategy(
        strategy_id="strategy-1",
        issue_type="table_parse_error",
        applicability="Repeated table parse repair.",
        steps=["match table signature", "restore cells", "verify lineage"],
        confidence=0.9,
        source_case_refs=["case-1"],
        status="promoted_memory",
    )
    connection = FakeConnection(fetchone_rows=[(strategy.to_dict(),), (2,)])
    repository = PostgresReaderRepairMemoryRepository(
        "postgresql://example",
        connection_factory=lambda: connection,
    )

    payload = repository.version_payload(
        namespace="research.reader_repair",
        object_type="strategy",
        object_id="strategy-1",
        version=1,
    )
    ref = repository.write_object(
        namespace="research.reader_repair",
        object_type="strategy",
        object_id="strategy-1",
        issue_type=payload["issue_type"],
        error_signature=None,
        successful=None,
        status=payload["status"],
        memory_kind="procedural",
        payload=payload,
        operation="rollback",
    )

    assert ref == "memory://research.reader_repair/strategy/strategy-1"
    assert connection.calls[-1][1][4] == "rollback"
    assert connection.commits == 1


def _issue() -> ReaderIssue:
    return ReaderIssue(
        issue_id="issue-table",
        paper_id="paper-1",
        issue_type="table_parse_error",
        error_signature="table_parse_error:build_reader_payload:pdf:missing_cells",
        symptom="Table dropped cells.",
        source_refs=["paper://paper-1/table-1"],
        payload_ref="reader-payload-1",
    )

