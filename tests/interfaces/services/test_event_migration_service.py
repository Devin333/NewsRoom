from __future__ import annotations

from pathlib import Path

import pytest

from framework.events.migration import (
    EventMigrationDryRun,
    MigrationSourceKind,
    MigrationSourceRecord,
)
import interfaces.services.event_migration_service as migration_service_module
from interfaces.services.event_migration_service import (
    EventMigrationApplicationError,
    EventMigrationApplicationService,
)


FIXTURES = Path(__file__).parents[2] / "fixtures" / "events" / "legacy"


def test_application_service_scans_all_five_source_kinds_without_mutation() -> None:
    source_paths = [
        FIXTURES / "valid" / "framework_event_record_v1.jsonl",
        FIXTURES / "valid" / "storage_event_record.jsonl",
        FIXTURES / "valid" / "checkpoints.json",
        FIXTURES / "valid" / "harness_history.jsonl",
    ]
    before = {path: path.read_bytes() for path in source_paths}
    postgres_record = MigrationSourceRecord(
        source_kind=MigrationSourceKind.POSTGRESQL_ROW,
        location="postgresql:workflow_events:run-postgres:0",
        value={
            "event_id": "evt-postgres-1",
            "event_type": "workflow_started",
            "occurred_at": "2026-07-15T01:00:00Z",
            "run_id": "run-postgres",
            "payload": {"run_id": "run-postgres"},
        },
    )
    factory = _CapturingPostgresFactory(postgres_record)
    service = EventMigrationApplicationService(
        postgres_reader_factory=factory,
        env={"NEWS_DATABASE_DSN": "postgresql://user:dsn-secret@localhost/newsroom"},
    )

    report = service.dry_run(
        legacy_run_jsonl=[source_paths[0]],
        local_event_records=[source_paths[1]],
        checkpoints=[source_paths[2]],
        harness_histories=[source_paths[3]],
        include_postgres=True,
    )

    assert {summary.source_kind for summary in report.source_summaries} == set(
        MigrationSourceKind
    )
    assert report.counts["quarantined"] == 0
    assert {path: path.read_bytes() for path in source_paths} == before
    assert factory.received_dsn.endswith("/newsroom")
    assert "dsn-secret" not in str(report.to_dict())


def test_application_service_fixture_report_covers_all_classifications() -> None:
    report = EventMigrationApplicationService(env={}).dry_run(
        legacy_run_jsonl=[FIXTURES / "invalid"],
    )

    assert report.counts["importable"] == 1
    assert report.counts["conflicting"] == 2
    assert report.counts["unknown_schema"] >= 1
    assert report.counts["missing_time"] == 1
    assert report.counts["quarantined"] >= 1


def test_application_service_verifies_before_after_source_fingerprints(
    monkeypatch,
) -> None:
    calls = 0
    real_fingerprint = migration_service_module.fingerprint_source_paths

    def changing_fingerprint(paths, *, suffix, source_kind):
        nonlocal calls
        calls += 1
        fingerprints = real_fingerprint(
            paths,
            suffix=suffix,
            source_kind=source_kind,
        )
        if calls > 4:
            return {path: "0" * 64 for path in fingerprints}
        return fingerprints

    monkeypatch.setattr(
        migration_service_module,
        "fingerprint_source_paths",
        changing_fingerprint,
    )
    service = EventMigrationApplicationService(env={})

    with pytest.raises(EventMigrationApplicationError, match="source changed"):
        service.dry_run(
            legacy_run_jsonl=[
                FIXTURES / "valid" / "framework_event_record_v1.jsonl"
            ]
        )

    assert calls == 8


def test_application_service_wraps_fingerprint_failure_without_exposing_path(
    tmp_path: Path,
) -> None:
    secret_path = tmp_path / "credential-secret" / "missing.json"

    with pytest.raises(EventMigrationApplicationError) as error:
        EventMigrationApplicationService(env={}).dry_run(checkpoints=[secret_path])

    message = str(error.value)
    assert "credential-secret" not in message
    assert message == "unable to read checkpoint migration source"


def test_application_service_detects_transient_source_change_during_scan(
    tmp_path: Path,
) -> None:
    path = tmp_path / "events.jsonl"
    original = (
        '{"event_id":"evt-original","event_type":"workflow_started",'
        '"occurred_at":"2026-07-15T01:00:00Z","run_id":"run-1",'
        '"payload":{"run_id":"run-1"}}\n'
    ).encode()
    changed = original.replace(b"evt-original", b"evt-changed-")
    path.write_bytes(original)

    class _MutatingScanner:
        def scan(self, records, *, fail_fast=False):
            path.write_bytes(changed)
            try:
                return EventMigrationDryRun().scan(records, fail_fast=fail_fast)
            finally:
                path.write_bytes(original)

    service = EventMigrationApplicationService(scanner=_MutatingScanner(), env={})

    with pytest.raises(EventMigrationApplicationError, match="unable to read"):
        service.dry_run(legacy_run_jsonl=[path])


def test_application_service_wraps_unexpected_postgres_factory_error() -> None:
    secret = "postgres-factory-secret"

    def failing_factory(dsn: str):
        raise RuntimeError(f"{dsn}:{secret}")

    service = EventMigrationApplicationService(
        postgres_reader_factory=failing_factory,
        env={"NEWS_DATABASE_DSN": "postgresql://user:password@host/db"},
    )

    with pytest.raises(EventMigrationApplicationError) as error:
        service.dry_run(include_postgres=True)

    message = str(error.value)
    assert message == "unable to read postgresql_row migration source"
    assert secret not in message
    assert "password" not in message


class _CapturingPostgresFactory:
    def __init__(self, record: MigrationSourceRecord) -> None:
        self.record = record
        self.received_dsn = ""

    def __call__(self, dsn: str):
        self.received_dsn = dsn
        return self

    def iter_records(self):
        yield self.record
