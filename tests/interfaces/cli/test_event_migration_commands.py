from __future__ import annotations

import json

from framework.events.migration import EventMigrationDryRun, MigrationSourceKind, MigrationSourceRecord
from interfaces.cli import news as news_cli
from interfaces.cli.commands import events as event_commands


def test_event_migration_cli_prints_machine_readable_report(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        event_commands,
        "EventMigrationApplicationService",
        _FakeMigrationService,
    )

    exit_code = news_cli.main(
        ["events", "migration-dry-run", "--legacy-run-jsonl", "events.jsonl", "--json"]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["dry_run"] is True
    assert payload["counts"]["importable"] == 1


def test_event_migration_cli_never_prints_dsn_or_secret(monkeypatch, capsys) -> None:
    secret = "cli-secret-must-not-leak"

    class _FailingService:
        def dry_run(self, **kwargs):
            raise RuntimeError(f"could not connect to postgresql://user:{secret}@host/db")

    monkeypatch.setattr(
        event_commands,
        "EventMigrationApplicationService",
        _FailingService,
    )

    exit_code = news_cli.main(["events", "migration-dry-run", "--postgres"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert secret not in captured.out + captured.err
    assert "postgresql://" not in captured.out + captured.err
    assert captured.err.strip() == "invalid migration dry-run request"


def test_event_migration_cli_returns_distinct_exit_for_quarantine(monkeypatch, capsys) -> None:
    class _QuarantinedMigrationService:
        def dry_run(self, **kwargs):
            return EventMigrationDryRun().scan(
                [
                    MigrationSourceRecord.issue(
                        MigrationSourceKind.LEGACY_RUN_JSONL,
                        "events.jsonl:1",
                        "invalid_json",
                    )
                ]
            )

    monkeypatch.setattr(
        event_commands,
        "EventMigrationApplicationService",
        _QuarantinedMigrationService,
    )

    exit_code = news_cli.main(
        ["events", "migration-dry-run", "--legacy-run-jsonl", "events.jsonl", "--json"]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["counts"]["quarantine_total"] == 1


def test_event_migration_cli_rejects_explicit_wrong_file_extension(
    tmp_path,
    capsys,
) -> None:
    wrong_file = tmp_path / "events.json"
    wrong_file.write_text("{}", encoding="utf-8")

    exit_code = news_cli.main(
        ["events", "migration-dry-run", "--legacy-run-jsonl", str(wrong_file)]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == ""
    assert captured.err.strip() == "invalid migration dry-run request"


def test_event_migration_backfill_and_shadow_compare_end_to_end(
    tmp_path,
    capsys,
) -> None:
    source = tmp_path / "events.jsonl"
    source.write_text(
        json.dumps(
            {
                "schema_version": "newsroom.event_record.v1",
                "event_id": "evt-cli-backfill",
                "event_type": "workflow_started",
                "occurred_at": "2026-07-16T01:00:00Z",
                "run_id": "run-cli",
                "payload": {"run_id": "run-cli"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    source_before = source.read_bytes()
    staging_root = tmp_path / "staging"
    backfill_report = tmp_path / "backfill.json"

    backfill_exit = news_cli.main(
        [
            "events",
            "migration-backfill",
            "--legacy-run-jsonl",
            str(source),
            "--staging-root",
            str(staging_root),
            "--report",
            str(backfill_report),
            "--report-id",
            "cli-backfill",
            "--json",
        ]
    )
    backfill_payload = json.loads(capsys.readouterr().out)

    assert backfill_exit == 0
    assert backfill_payload["status"] == "succeeded"
    assert backfill_payload["counts"]["imported"] == 1
    assert backfill_report.is_file()
    assert source.read_bytes() == source_before

    shadow_report = tmp_path / "shadow.json"
    shadow_exit = news_cli.main(
        [
            "events",
            "migration-shadow-compare",
            "--staging-root",
            str(staging_root),
            "--report",
            str(backfill_report),
            "--report-id",
            "cli-backfill",
            "--shadow-report",
            str(shadow_report),
            "--json",
        ]
    )
    shadow_payload = json.loads(capsys.readouterr().out)

    assert shadow_exit == 0
    assert shadow_payload["cutover_ready"] is True
    assert shadow_payload["expected_event_count"] == 1
    assert shadow_payload["actual_event_count"] == 1
    assert shadow_report.is_file()
    assert source.read_bytes() == source_before


def test_event_migration_backfill_rejects_active_artifact_root(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    source = tmp_path / "events.jsonl"
    source.write_text("{}\n", encoding="utf-8")
    active_root = tmp_path / "active"
    monkeypatch.setenv("NEWS_ARTIFACT_ROOT", str(active_root))

    exit_code = news_cli.main(
        [
            "events",
            "migration-backfill",
            "--legacy-run-jsonl",
            str(source),
            "--staging-root",
            str(active_root),
            "--report",
            str(tmp_path / "backfill.json"),
            "--report-id",
            "unsafe-staging",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err.strip() == (
        "migration staging root must differ from the active artifact root"
    )


def test_event_migration_backfill_error_does_not_expose_credentials(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    secret = "backfill-secret-must-not-leak"

    def failing_service(args):
        raise RuntimeError(f"postgresql://user:{secret}@host/database")

    monkeypatch.setattr(event_commands, "_backfill_service", failing_service)

    exit_code = news_cli.main(
        [
            "events",
            "migration-backfill",
            "--postgres",
            "--staging-root",
            str(tmp_path / "staging"),
            "--report",
            str(tmp_path / "backfill.json"),
            "--report-id",
            "secret-error",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert secret not in captured.out + captured.err
    assert "postgresql://" not in captured.out + captured.err
    assert captured.err.strip() == "invalid migration backfill request"


class _FakeMigrationService:
    def dry_run(self, **kwargs):
        return EventMigrationDryRun().scan(
            [
                MigrationSourceRecord(
                    source_kind=MigrationSourceKind.LEGACY_RUN_JSONL,
                    location="events.jsonl:1",
                    value={
                        "event_id": "evt-1",
                        "event_type": "workflow_started",
                        "occurred_at": "2026-07-15T01:00:00Z",
                        "run_id": "run-1",
                        "payload": {"run_id": "run-1"},
                    },
                )
            ]
        )
