from __future__ import annotations

import argparse
import json
import sys

from interfaces.services.event_migration_service import (
    EventMigrationApplicationError,
    EventMigrationApplicationService,
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


def _has_source(args: argparse.Namespace) -> bool:
    return bool(
        args.legacy_run_jsonl
        or args.local_event_records
        or args.checkpoints
        or args.harness_histories
        or args.postgres
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


__all__ = ["event_migration_dry_run", "register"]
