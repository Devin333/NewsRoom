from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from framework.events.migration_backfill import MigrationBackfillError
from infrastructure.storage.events.factory import (
    DEFAULT_ARTIFACT_ROOT,
    durable_event_storage_from_env,
)
from infrastructure.storage.events.migration_reports import (
    JsonMigrationBackfillReportStore,
    MigrationReportStoreError,
    write_migration_shadow_report,
)
from interfaces.services.event_migration_service import (
    EventMigrationApplicationError,
    EventMigrationApplicationService,
    EventMigrationBackfillApplicationService,
    MigrationSourceSelection,
)


def register(subparsers: argparse._SubParsersAction) -> None:
    events_parser = subparsers.add_parser(
        "events",
        help="Inspect and migrate durable event history",
    )
    events_subparsers = events_parser.add_subparsers(
        dest="events_command",
        required=True,
    )
    migration_parser = events_subparsers.add_parser(
        "migration-dry-run",
        help="Classify legacy event history without modifying source data",
    )
    migration_parser.add_argument(
        "--legacy-run-jsonl",
        action="append",
        default=[],
        metavar="PATH",
        help="Legacy run events.jsonl file or directory (repeatable)",
    )
    migration_parser.add_argument(
        "--local-event-records",
        action="append",
        default=[],
        metavar="PATH",
        help="Local event-record JSONL file or directory (repeatable)",
    )
    migration_parser.add_argument(
        "--checkpoints",
        action="append",
        default=[],
        metavar="PATH",
        help="Checkpoint JSON file or directory (repeatable)",
    )
    migration_parser.add_argument(
        "--harness-histories",
        action="append",
        default=[],
        metavar="PATH",
        help="Harness history JSONL file or directory (repeatable)",
    )
    migration_parser.add_argument(
        "--postgres",
        action="store_true",
        help="Read event rows from NEWS_DATABASE_DSN in a read-only transaction",
    )
    migration_parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop after the first quarantined source record",
    )
    migration_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON",
    )
    migration_parser.set_defaults(handler=event_migration_dry_run)

    backfill_parser = events_subparsers.add_parser(
        "migration-backfill",
        help="Import a verified legacy snapshot into an isolated staging store",
    )
    _add_source_arguments(backfill_parser)
    backfill_parser.add_argument(
        "--staging-root",
        required=True,
        metavar="PATH",
        help="Isolated local root for the canonical staging SQLite store",
    )
    backfill_parser.add_argument(
        "--report",
        required=True,
        metavar="PATH",
        help="Checksum-protected JSON progress report path",
    )
    backfill_parser.add_argument(
        "--report-id",
        required=True,
        help="Stable identifier used to resume this exact source snapshot",
    )
    backfill_parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Fail if the progress report already exists",
    )
    backfill_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON",
    )
    backfill_parser.set_defaults(handler=event_migration_backfill)

    shadow_parser = events_subparsers.add_parser(
        "migration-shadow-compare",
        help="Compare a completed backfill report with staging history read-only",
    )
    shadow_parser.add_argument("--staging-root", required=True, metavar="PATH")
    shadow_parser.add_argument("--report", required=True, metavar="PATH")
    shadow_parser.add_argument("--report-id", required=True)
    shadow_parser.add_argument("--shadow-report", required=True, metavar="PATH")
    shadow_parser.add_argument("--json", action="store_true")
    shadow_parser.set_defaults(handler=event_migration_shadow_compare)


def event_migration_dry_run(args: argparse.Namespace) -> int:
    if not _has_source(args):
        print("migration dry-run requires at least one source", file=sys.stderr)
        return 1
    try:
        report = EventMigrationApplicationService().dry_run(
            legacy_run_jsonl=args.legacy_run_jsonl,
            local_event_records=args.local_event_records,
            checkpoints=args.checkpoints,
            harness_histories=args.harness_histories,
            include_postgres=args.postgres,
            fail_fast=args.fail_fast,
        )
    except Exception as exc:
        # Source/adapter exception messages may contain a DSN, credentials, or
        # raw record fragments.  The CLI boundary always emits a bounded error.
        print(_safe_error(exc), file=sys.stderr)
        return 1
    payload = report.to_dict()
    counts = payload["counts"]
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print("dry_run=true")
        print(f"halted={str(payload['halted']).lower()}")
        for name in (
            "scanned",
            "importable",
            "duplicate",
            "conflicting",
            "unknown_schema",
            "missing_time",
            "quarantined",
            "quarantine_total",
        ):
            print(f"{name}={counts[name]}")
        for source in payload["sources"]:
            print(
                f"- source={source['source_kind']} scanned={source['scanned']} "
                f"importable={source['importable']} duplicate={source['duplicate']} "
                f"quarantined={source['quarantined']} "
                f"quarantine_total={source['quarantine_total']}"
            )
    return 2 if counts["quarantine_total"] else 0


def event_migration_backfill(args: argparse.Namespace) -> int:
    if not _has_source(args):
        print("migration backfill requires at least one source", file=sys.stderr)
        return 1
    try:
        service = _backfill_service(args)
        report = service.backfill(
            _source_selection(args),
            report_id=args.report_id,
            resume=not args.no_resume,
        )
    except Exception as exc:
        print(_safe_backfill_error(exc), file=sys.stderr)
        return 1
    payload = report.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"status={payload['status']}")
        print(f"report_id={payload['report_id']}")
        print(f"report_checksum={payload['report_checksum']}")
        for name, value in payload["counts"].items():
            print(f"{name}={value}")
    return 2 if payload["counts"]["quarantined"] else 0


def event_migration_shadow_compare(args: argparse.Namespace) -> int:
    try:
        report = _backfill_service(args).shadow_compare(report_id=args.report_id)
        write_migration_shadow_report(args.shadow_report, report)
    except Exception as exc:
        print(_safe_backfill_error(exc), file=sys.stderr)
        return 1
    payload = report.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"cutover_ready={str(payload['cutover_ready']).lower()}")
        print(f"report_checksum={payload['report_checksum']}")
        print(f"expected_event_count={payload['expected_event_count']}")
        print(f"actual_event_count={payload['actual_event_count']}")
        print(f"mismatch_count={len(payload['mismatches'])}")
    return 0 if payload["cutover_ready"] else 2


def _has_source(args: argparse.Namespace) -> bool:
    return bool(
        args.legacy_run_jsonl
        or args.local_event_records
        or args.checkpoints
        or args.harness_histories
        or args.postgres
    )


def _add_source_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--legacy-run-jsonl", action="append", default=[])
    parser.add_argument("--local-event-records", action="append", default=[])
    parser.add_argument("--checkpoints", action="append", default=[])
    parser.add_argument("--harness-histories", action="append", default=[])
    parser.add_argument(
        "--postgres",
        action="store_true",
        help="Read NEWS_DATABASE_DSN as a read-only source",
    )


def _source_selection(args: argparse.Namespace) -> MigrationSourceSelection:
    return MigrationSourceSelection.from_inputs(
        legacy_run_jsonl=args.legacy_run_jsonl,
        local_event_records=args.local_event_records,
        checkpoints=args.checkpoints,
        harness_histories=args.harness_histories,
        include_postgres=args.postgres,
    )


def _backfill_service(
    args: argparse.Namespace,
) -> EventMigrationBackfillApplicationService:
    staging_root = Path(args.staging_root).expanduser().resolve()
    active_root = Path(
        str(os.environ.get("NEWS_ARTIFACT_ROOT") or DEFAULT_ARTIFACT_ROOT)
    ).expanduser().resolve()
    if staging_root == active_root:
        raise EventMigrationApplicationError(
            "migration staging root must differ from the active artifact root"
        )
    storage = durable_event_storage_from_env(
        artifact_root=staging_root,
        env={},
    )
    return EventMigrationBackfillApplicationService(
        source_service=EventMigrationApplicationService(),
        staging_store=storage.event_store,
        schema_catalog=storage.schema_catalog,
        report_store=JsonMigrationBackfillReportStore(args.report),
    )


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, FileNotFoundError):
        return "migration source path does not exist"
    if isinstance(exc, EventMigrationApplicationError):
        return str(exc)
    message = str(exc)
    if "NEWS_DATABASE_DSN" in message:
        return "PostgreSQL migration scan requires NEWS_DATABASE_DSN"
    return "invalid migration dry-run request"


def _safe_backfill_error(exc: Exception) -> str:
    if isinstance(exc, FileNotFoundError):
        return "migration source path does not exist"
    if isinstance(exc, EventMigrationApplicationError):
        return str(exc)
    if isinstance(exc, (MigrationBackfillError, MigrationReportStoreError)):
        return str(exc)
    message = str(exc)
    if "NEWS_DATABASE_DSN" in message:
        return "PostgreSQL migration scan requires NEWS_DATABASE_DSN"
    return "invalid migration backfill request"


__all__ = [
    "event_migration_backfill",
    "event_migration_dry_run",
    "event_migration_shadow_compare",
    "register",
]
