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
