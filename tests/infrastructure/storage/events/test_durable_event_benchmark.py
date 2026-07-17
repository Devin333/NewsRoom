from __future__ import annotations

from pathlib import Path

import pytest

from scripts.durable_event_benchmark import (
    CANONICAL_EVENT_TARGET_BYTES,
    EVIDENCE_SCHEMA,
    BenchmarkFailure,
    _cleanup_postgres_scopes,
    _PostgresCleanupScope,
    _validate_postgres_target,
    run_benchmark,
    verify_evidence,
)


def test_smoke_benchmark_uses_durable_runtime_and_records_nonqualifying_evidence(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    evidence_path = tmp_path / "evidence.json"

    evidence = run_benchmark(
        workspace=workspace,
        postgres_dsn=None,
        duration_seconds=1,
        read_replay_event_count=25,
        evidence_path=evidence_path,
        qualification=False,
    )

    assert evidence["schema"] == EVIDENCE_SCHEMA
    assert evidence["overall_status"] == "smoke_passed"
    assert all(evidence["gates"]["correctness"].values())
    assert evidence["gates"]["slo"][
        "sqlite_dispatcher_recovery_within_two_leases"
    ]
    assert not evidence["gates"]["slo"][
        "postgres_dispatcher_recovery_within_two_leases"
    ]
    assert not evidence["gates"]["qualification"][
        "postgres_same_stream_workload_executed"
    ]

    append = evidence["append_results"][0]
    assert append["committed"] == 25
    assert append["committed_recovery"]["all_committed_events_readable"]
    assert append["canonical_event_size_bytes"]["mean"] == pytest.approx(
        CANONICAL_EVENT_TARGET_BYTES,
        rel=0.05,
    )
    assert evidence["limit_probes"]["size"]["passed"]
    assert evidence["limit_probes"]["backlog"][0]["passed"]
    assert evidence["delivery_results"][0]["acknowledged"] == 100
    assert evidence["delivery_results"][0]["passed"]
    assert evidence["dispatcher_recovery"][0]["passed"]
    assert evidence_path.exists()

    verified = verify_evidence(evidence_path, allow_smoke=True)
    assert verified["evidence_checksum"] == evidence["evidence_checksum"]
    with pytest.raises(BenchmarkFailure, match="qualified success"):
        verify_evidence(evidence_path)


def test_qualification_rejects_partial_workload_before_creating_workspace(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"

    with pytest.raises(BenchmarkFailure, match="fixed 600 second workload"):
        run_benchmark(
            workspace=workspace,
            postgres_dsn=None,
            duration_seconds=1,
            read_replay_event_count=25,
            qualification=True,
        )

    assert not workspace.exists()


def test_postgres_cleanup_uses_only_exact_generated_scope_and_verifies_zero_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import psycopg

    connection = _CleanupConnection()
    monkeypatch.setattr(psycopg, "connect", lambda dsn: connection)
    scope = _PostgresCleanupScope(
        tenant_id="tenant-event-benchmark:exact-scope",
        subscription_ids=("benchmark-delivery:exact-scope",),
        stream_ids=("benchmark:exact-scope:0", "benchmark:exact-scope:1"),
    )

    evidence = _cleanup_postgres_scopes("redacted-test-dsn", (scope,))

    assert evidence["executed"]
    assert evidence["passed"]
    assert evidence["scope_count"] == 1
    assert evidence["rows_after_cleanup"] == 0
    assert len(connection.cursor_instance.executions) == 28
    for statement, params in connection.cursor_instance.executions:
        assert " LIKE " not in statement.upper()
        assert "benchmark:%" not in repr(params)
        assert "tenant-event-benchmark:%" not in repr(params)
    assert all(
        count == 0
        for count in evidence["scopes"][0]["rows_after_cleanup"].values()
    )


def test_qualification_requires_isolated_postgres_database() -> None:
    with pytest.raises(BenchmarkFailure, match="isolated test or benchmark"):
        _validate_postgres_target(
            {"database_name": "NewsRoom"},
            qualification=True,
        )

    _validate_postgres_target(
        {"database_name": "newsroom_event_benchmark"},
        qualification=True,
    )
    _validate_postgres_target(
        {"database_name": "NewsRoom"},
        qualification=False,
    )


class _CleanupCursor:
    def __init__(self) -> None:
        self.executions: list[tuple[str, object]] = []
        self.rowcount = 0
        self._result = (0,)

    def __enter__(self) -> _CleanupCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, statement: str, params: object) -> None:
        self.executions.append((statement, params))
        if statement.startswith("DELETE"):
            self.rowcount = 1
        else:
            self.rowcount = 1
            self._result = (0,)

    def fetchone(self) -> tuple[int]:
        return self._result


class _CleanupConnection:
    def __init__(self) -> None:
        self.cursor_instance = _CleanupCursor()
        self.committed = False

    def __enter__(self) -> _CleanupConnection:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def cursor(self) -> _CleanupCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.committed = True
