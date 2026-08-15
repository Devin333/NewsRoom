from __future__ import annotations

from datetime import UTC, datetime

import pytest

from business.research.domain import ReaderIssue
from business.research.domain.reader_repair import ReaderRepairStrategy
from infrastructure.storage.postgres.repair_memory_repository import (
    PostgresReaderRepairMemoryCommitConflictError,
    PostgresReaderRepairMemoryObjectWrite,
    PostgresReaderRepairMemoryRepository,
)
from tests.business.research.reader_repair._fixtures import make_repair_case


CHECKSUM_A = f"sha256:{'a' * 64}"
CHECKSUM_B = f"sha256:{'b' * 64}"
CHECKSUM_C = f"sha256:{'c' * 64}"
CHECKSUM_D = f"sha256:{'d' * 64}"
COMMITTED_AT = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.connection.calls.append((sql, params))
        if self.connection.fail_on_sql and self.connection.fail_on_sql in sql:
            self.connection.fail_matches += 1
            if self.connection.fail_matches == self.connection.fail_on_occurrence:
                raise RuntimeError("injected reader repair memory write failure")

    def fetchone(self):
        if self.connection.fetchone_rows:
            return self.connection.fetchone_rows.pop(0)
        return None

    def fetchall(self):
        if self.connection.fetchall_rows:
            return list(self.connection.fetchall_rows.pop(0))
        return []


class FakeConnection:
    def __init__(
        self,
        *,
        fetchone_rows=None,
        fetchall_rows=None,
        fail_on_sql=None,
        fail_on_occurrence=1,
    ):
        self.calls = []
        self.commits = 0
        self.rollbacks = 0
        self.fetchone_rows = list(fetchone_rows or [])
        self.fetchall_rows = list(fetchall_rows or [])
        self.fail_on_sql = fail_on_sql
        self.fail_on_occurrence = fail_on_occurrence
        self.fail_matches = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


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


def test_postgres_reader_repair_memory_repository_commits_bundle_atomically() -> None:
    connection = FakeConnection(
        fetchone_rows=[None, (2,), (4,), (COMMITTED_AT,)]
    )
    repository = _repository(connection)

    record = _commit_bundle(repository)

    executed_sql = "\n".join(sql for sql, _params in connection.calls)
    assert record.case_object_id == "case-1"
    assert record.case_version == 2
    assert record.strategy_versions == (("strategy-1", 4),)
    assert record.committed_at == COMMITTED_AT
    assert executed_sql.count("INSERT INTO reader_repair_memory_objects") == 2
    assert executed_sql.count("INSERT INTO reader_repair_memory_versions") == 2
    assert "INSERT INTO reader_repair_memory_commits" in executed_sql
    assert executed_sql.count("INSERT INTO reader_repair_memory_commit_members") == 2
    assert connection.commits == 1
    assert connection.rollbacks == 0


def test_postgres_reader_repair_memory_repository_recovers_idempotent_commit() -> None:
    header = (
        CHECKSUM_A,
        "request-1",
        "run-1",
        "effect-1",
        CHECKSUM_B,
        CHECKSUM_C,
        CHECKSUM_D,
        "research.reader_repair",
        COMMITTED_AT,
    )
    members = [
        (0, "case", "case-1", 2),
        (1, "strategy", "strategy-1", 4),
    ]
    connection = FakeConnection(
        fetchone_rows=[header],
        fetchall_rows=[members],
    )
    repository = _repository(connection)

    record = _commit_bundle(repository)

    executed_sql = "\n".join(sql for sql, _params in connection.calls)
    assert record.case_version == 2
    assert record.strategy_versions == (("strategy-1", 4),)
    assert "INSERT INTO reader_repair_memory_objects" not in executed_sql
    assert "INSERT INTO reader_repair_memory_versions" not in executed_sql
    assert "INSERT INTO reader_repair_memory_commits" not in executed_sql
    assert connection.commits == 1
    assert connection.rollbacks == 0


def test_postgres_reader_repair_memory_repository_rejects_idempotency_conflict() -> None:
    header = (
        CHECKSUM_D,
        "request-1",
        "run-1",
        "effect-1",
        CHECKSUM_B,
        CHECKSUM_C,
        CHECKSUM_D,
        "research.reader_repair",
        COMMITTED_AT,
    )
    connection = FakeConnection(
        fetchone_rows=[header],
        fetchall_rows=[[(0, "case", "case-1", 1)]],
    )
    repository = _repository(connection)

    with pytest.raises(
        PostgresReaderRepairMemoryCommitConflictError,
        match="idempotency key conflicts",
    ):
        _commit_bundle(repository, strategies=())

    assert connection.commits == 0
    assert connection.rollbacks == 1


def test_postgres_reader_repair_memory_repository_rolls_back_partial_bundle() -> None:
    connection = FakeConnection(
        fetchone_rows=[None, (1,), (1,)],
        fail_on_sql="INSERT INTO reader_repair_memory_versions",
        fail_on_occurrence=2,
    )
    repository = _repository(connection)

    with pytest.raises(
        RuntimeError,
        match="injected reader repair memory write failure",
    ):
        _commit_bundle(repository)

    assert connection.commits == 0
    assert connection.rollbacks == 1


def test_postgres_reader_repair_memory_repository_locks_objects_canonically() -> None:
    connection = FakeConnection(
        fetchone_rows=[None, (1,), (1,), (1,), (COMMITTED_AT,)]
    )
    repository = _repository(connection)
    strategies = (
        _strategy_write("strategy-z"),
        _strategy_write("strategy-a"),
    )

    _commit_bundle(repository, strategies=strategies)

    lock_keys = [
        params[0]
        for sql, params in connection.calls
        if "pg_advisory_xact_lock" in sql
    ]
    assert lock_keys == [
        "reader-repair-memory-commit:idempotency-1",
        "reader-repair-memory-object:research.reader_repair:case:case-1",
        "reader-repair-memory-object:research.reader_repair:strategy:strategy-a",
        "reader-repair-memory-object:research.reader_repair:strategy:strategy-z",
    ]


def test_postgres_reader_repair_memory_object_write_copies_nested_payload() -> None:
    payload = {"nested": {"items": ["original"]}}

    write = PostgresReaderRepairMemoryObjectWrite(
        object_type="case",
        object_id="case-1",
        issue_type="table_parse_error",
        error_signature="signature",
        successful=True,
        status=None,
        memory_kind="episodic",
        payload=payload,
    )
    payload["nested"]["items"].append("mutated")

    assert write.payload == {"nested": {"items": ["original"]}}


def _repository(connection: FakeConnection) -> PostgresReaderRepairMemoryRepository:
    return PostgresReaderRepairMemoryRepository(
        "postgresql://example",
        connection_factory=lambda: connection,
    )


def _commit_bundle(
    repository: PostgresReaderRepairMemoryRepository,
    *,
    strategies: tuple[PostgresReaderRepairMemoryObjectWrite, ...] | None = None,
):
    return repository.commit_bundle(
        idempotency_key="idempotency-1",
        request_checksum=CHECKSUM_A,
        request_id="request-1",
        run_id="run-1",
        terminal_effect_id="effect-1",
        authorization_ref=CHECKSUM_B,
        identity_scope_ref=CHECKSUM_C,
        subject_scope_ref=CHECKSUM_D,
        namespace="research.reader_repair",
        repair_case=_case_write(),
        strategies=(_strategy_write("strategy-1"),)
        if strategies is None
        else strategies,
    )


def _case_write() -> PostgresReaderRepairMemoryObjectWrite:
    return PostgresReaderRepairMemoryObjectWrite(
        object_type="case",
        object_id="case-1",
        issue_type="table_parse_error",
        error_signature="table-error",
        successful=True,
        status=None,
        memory_kind="episodic",
        payload={"repair_case_id": "case-1"},
    )


def _strategy_write(object_id: str) -> PostgresReaderRepairMemoryObjectWrite:
    return PostgresReaderRepairMemoryObjectWrite(
        object_type="strategy",
        object_id=object_id,
        issue_type="table_parse_error",
        error_signature=None,
        successful=None,
        status="promoted_memory",
        memory_kind="procedural",
        payload={"strategy_id": object_id},
    )


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
