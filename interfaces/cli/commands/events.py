from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

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


_QUARANTINE_REASONS = (
    "unknown_envelope_schema",
    "unknown_data_schema",
    "schema_validation_failed",
    "missing_occurred_at",
    "invalid_occurred_at",
    "context_conflict",
    "identity_collision",
    "corrupt_record",
    "unsupported_legacy_mapping",
    "upcast_failed",
    "security_scope_ambiguous",
)
_QUARANTINE_DISPOSITIONS = ("pending", "released", "rejected")
_REPLAY_MODES = ("rebuild_state", "verify_history", "redeliver")
_REPLAY_STATUSES = ("pending", "running", "succeeded", "failed")
_DEAD_LETTER_DISPOSITIONS = ("open", "requeued", "resolved")


def event_operator_service_from_env() -> Any:
    # Keep operator-only composition lazy so migration commands remain usable
    # in deployments that intentionally omit event operator capabilities.
    from interfaces.services.event_operator_factory import (
        event_operator_service_from_env as factory,
    )

    return factory()


def register(subparsers: argparse._SubParsersAction) -> None:
    events_parser = subparsers.add_parser(
        "events",
        help="Inspect, operate, and migrate durable event history",
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

    _register_operator_commands(events_subparsers)


def _register_operator_commands(
    events_subparsers: argparse._SubParsersAction,
) -> None:
    quarantine_parser = events_subparsers.add_parser(
        "quarantine",
        help="Inspect tenant-scoped quarantined event records",
    )
    quarantine_subparsers = quarantine_parser.add_subparsers(
        dest="quarantine_command",
        required=True,
    )
    quarantine_list_parser = quarantine_subparsers.add_parser(
        "list",
        help="List quarantined event records",
    )
    quarantine_list_parser.add_argument("--reason", choices=_QUARANTINE_REASONS)
    quarantine_list_parser.add_argument(
        "--disposition",
        choices=_QUARANTINE_DISPOSITIONS,
    )
    _add_page_arguments(quarantine_list_parser)
    quarantine_list_parser.set_defaults(handler=event_quarantine_list)
    quarantine_show_parser = quarantine_subparsers.add_parser(
        "show",
        help="Show one quarantined event record",
    )
    quarantine_show_parser.add_argument("quarantine_id")
    _add_json_argument(quarantine_show_parser)
    quarantine_show_parser.set_defaults(handler=event_quarantine_show)

    replay_parser = events_subparsers.add_parser(
        "replay-reports",
        help="Inspect tenant-scoped deterministic replay reports",
    )
    replay_subparsers = replay_parser.add_subparsers(
        dest="replay_reports_command",
        required=True,
    )
    replay_list_parser = replay_subparsers.add_parser(
        "list",
        help="List deterministic replay reports",
    )
    replay_list_parser.add_argument("--source-stream-id")
    replay_list_parser.add_argument("--mode", choices=_REPLAY_MODES)
    replay_list_parser.add_argument("--status", choices=_REPLAY_STATUSES)
    _add_page_arguments(replay_list_parser)
    replay_list_parser.set_defaults(handler=event_replay_reports_list)
    replay_show_parser = replay_subparsers.add_parser(
        "show",
        help="Show one deterministic replay report",
    )
    replay_show_parser.add_argument("replay_id")
    _add_json_argument(replay_show_parser)
    replay_show_parser.set_defaults(handler=event_replay_report_show)

    dead_letters_parser = events_subparsers.add_parser(
        "dead-letters",
        help="Inspect and operate tenant-scoped dead letters",
    )
    dead_letters_subparsers = dead_letters_parser.add_subparsers(
        dest="dead_letters_command",
        required=True,
    )
    dead_letters_list_parser = dead_letters_subparsers.add_parser(
        "list",
        help="List dead letters",
    )
    dead_letters_list_parser.add_argument("--subscription-id")
    dead_letters_list_parser.add_argument(
        "--subscription-version",
        type=_positive_int,
    )
    dead_letters_list_parser.add_argument(
        "--disposition",
        choices=_DEAD_LETTER_DISPOSITIONS,
    )
    _add_page_arguments(dead_letters_list_parser)
    dead_letters_list_parser.set_defaults(handler=event_dead_letters_list)
    dead_letters_show_parser = dead_letters_subparsers.add_parser(
        "show",
        help="Show one dead letter",
    )
    dead_letters_show_parser.add_argument("dead_letter_id")
    _add_json_argument(dead_letters_show_parser)
    dead_letters_show_parser.set_defaults(handler=event_dead_letter_show)
    dead_letters_resolve_parser = dead_letters_subparsers.add_parser(
        "resolve",
        help="Terminally resolve one dead letter",
    )
    dead_letters_resolve_parser.add_argument("dead_letter_id")
    _add_mutation_arguments(dead_letters_resolve_parser)
    dead_letters_resolve_parser.set_defaults(handler=event_dead_letter_resolve)
    dead_letters_requeue_parser = dead_letters_subparsers.add_parser(
        "requeue",
        help="Create an idempotent late-repair delivery generation",
    )
    dead_letters_requeue_parser.add_argument("dead_letter_id")
    dead_letters_requeue_parser.add_argument("--subscription-id", required=True)
    dead_letters_requeue_parser.add_argument(
        "--subscription-version",
        required=True,
        type=_positive_int,
    )
    _add_mutation_arguments(dead_letters_requeue_parser)
    dead_letters_requeue_parser.set_defaults(handler=event_dead_letter_requeue)

    consumer_status_parser = events_subparsers.add_parser(
        "consumer-status",
        help="Inspect consumer lag, pending work, and checkpoint status",
    )
    consumer_status_parser.add_argument("--subscription-id", required=True)
    consumer_status_parser.add_argument(
        "--subscription-version",
        required=True,
        type=_positive_int,
    )
    consumer_status_parser.add_argument("--stream-id", required=True)
    _add_json_argument(consumer_status_parser)
    consumer_status_parser.set_defaults(handler=event_consumer_status)

    projection_status_parser = events_subparsers.add_parser(
        "projection-status",
        help="Inspect one run event projection against durable history",
    )
    projection_status_parser.add_argument("run_id")
    _add_json_argument(projection_status_parser)
    projection_status_parser.set_defaults(handler=event_projection_status)


def _add_page_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--cursor", help="Opaque cursor returned by the previous page")
    parser.add_argument("--limit", type=_page_limit, default=100)
    _add_json_argument(parser)


def _add_json_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON",
    )


def _add_mutation_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--reason", required=True, help="Auditable operator reason")
    parser.add_argument(
        "--yes",
        action="store_true",
        required=True,
        help="Confirm the requested mutation",
    )
    _add_json_argument(parser)


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


def event_quarantine_list(args: argparse.Namespace) -> int:
    return _run_operator_command(
        args,
        lambda service: service.list_quarantine(
            reason=args.reason,
            disposition=args.disposition,
            cursor=args.cursor,
            limit=args.limit,
        ),
    )


def event_quarantine_show(args: argparse.Namespace) -> int:
    return _run_operator_command(
        args,
        lambda service: service.get_quarantine(args.quarantine_id),
    )


def event_replay_reports_list(args: argparse.Namespace) -> int:
    return _run_operator_command(
        args,
        lambda service: service.list_replay_reports(
            source_stream_id=args.source_stream_id,
            mode=args.mode,
            status=args.status,
            cursor=args.cursor,
            limit=args.limit,
        ),
    )


def event_replay_report_show(args: argparse.Namespace) -> int:
    return _run_operator_command(
        args,
        lambda service: service.get_replay_report(args.replay_id),
    )


def event_dead_letters_list(args: argparse.Namespace) -> int:
    if args.subscription_version is not None and args.subscription_id is None:
        print(
            "--subscription-version requires --subscription-id",
            file=sys.stderr,
        )
        return 1
    return _run_operator_command(
        args,
        lambda service: service.list_dead_letters(
            subscription_id=args.subscription_id,
            subscription_version=args.subscription_version,
            disposition=args.disposition,
            cursor=args.cursor,
            limit=args.limit,
        ),
    )


def event_dead_letter_show(args: argparse.Namespace) -> int:
    return _run_operator_command(
        args,
        lambda service: service.get_dead_letter(args.dead_letter_id),
    )


def event_dead_letter_resolve(args: argparse.Namespace) -> int:
    if not args.yes:
        return _confirmation_required()
    return _run_operator_command(
        args,
        lambda service: service.resolve_dead_letter(
            args.dead_letter_id,
            operator_reason=args.reason,
        ),
    )


def event_dead_letter_requeue(args: argparse.Namespace) -> int:
    if not args.yes:
        return _confirmation_required()
    return _run_operator_command(
        args,
        lambda service: service.requeue_dead_letter(
            args.dead_letter_id,
            subscription_id=args.subscription_id,
            subscription_version=args.subscription_version,
            operator_reason=args.reason,
            idempotency_acknowledged=args.yes,
        ),
    )


def event_consumer_status(args: argparse.Namespace) -> int:
    return _run_operator_command(
        args,
        lambda service: service.get_consumer_status(
            subscription_id=args.subscription_id,
            subscription_version=args.subscription_version,
            stream_id=args.stream_id,
        ),
    )


def event_projection_status(args: argparse.Namespace) -> int:
    return _run_operator_command(
        args,
        lambda service: service.get_projection_status(args.run_id),
    )


def _run_operator_command(
    args: argparse.Namespace,
    operation: Callable[[Any], Mapping[str, Any]],
) -> int:
    try:
        service = event_operator_service_from_env()
        raw_payload = operation(service)
        if not isinstance(raw_payload, Mapping):
            raise TypeError("event operator service returned an invalid payload")
        payload = dict(raw_payload)
        encoded_payload = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
        )
        rendered = encoded_payload if args.json else _render_operator_text(payload)
    except Exception:
        # Composition and adapter failures can contain DSNs, local paths, raw
        # source fragments, or credentials. Keep this public boundary bounded.
        print("event operator command failed", file=sys.stderr)
        return 1
    print(rendered)
    if payload.get("availability") == "unavailable" or payload.get("status") == "unavailable":
        return 2
    if payload.get("found") is False:
        return 1
    return 0


def _confirmation_required() -> int:
    print("event operator mutation requires --yes", file=sys.stderr)
    return 1


def _render_operator_text(payload: Mapping[str, Any]) -> str:
    lines: list[str] = []
    for field in (
        "availability",
        "status",
        "tenant_id",
        "found",
        "run_id",
        "stream_id",
        "durable_high_watermark",
        "projection_high_watermark",
        "projection_event_count",
        "projection_checksum",
        "next_cursor",
        "unavailable_reason_class",
    ):
        if field in payload:
            lines.append(f"{field}={_format_text_value(payload[field])}")

    items = payload.get("items")
    if isinstance(items, list):
        lines.append(f"item_count={len(items)}")
        lines.extend(f"- {_summarize_operator_record(item)}" for item in items)

    for field in (
        "quarantine",
        "replay_report",
        "dead_letter",
        "delivery",
        "subscription",
        "stats",
        "checkpoint",
    ):
        value = payload.get(field)
        if isinstance(value, Mapping):
            summary = _summarize_operator_record(value, prefix=field)
            if summary:
                lines.append(summary)
    return "\n".join(lines) if lines else "status=ok"


def _summarize_operator_record(
    value: Any,
    *,
    prefix: str | None = None,
) -> str:
    if not isinstance(value, Mapping):
        return "record=invalid"
    fields: list[str] = []
    for field in (
        "quarantine_id",
        "replay_id",
        "dead_letter_id",
        "delivery_id",
        "event_id",
        "subscription_id",
        "subscription_version",
        "stream_id",
        "run_id",
        "status",
        "state",
        "disposition",
        "reason",
        "reason_class",
        "attempt_count",
        "pending_count",
        "lag",
        "oldest_pending_age_seconds",
        "late_repair_pending_count",
        "warning_threshold_reached",
        "capacity_remaining",
        "highest_contiguous_terminal_sequence",
        "last_event_id",
        "stream_sequence",
    ):
        field_value = value.get(field)
        if field_value is not None and not isinstance(field_value, (dict, list)):
            name = f"{prefix}.{field}" if prefix else field
            fields.append(f"{name}={_format_text_value(field_value)}")
    return " ".join(fields) if fields else (f"{prefix}=present" if prefix else "record=present")


def _format_text_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _page_limit(value: str) -> int:
    parsed = _positive_int(value)
    if parsed > 1_000:
        raise argparse.ArgumentTypeError("must be at most 1000")
    return parsed


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
    "event_consumer_status",
    "event_dead_letter_requeue",
    "event_dead_letter_resolve",
    "event_dead_letter_show",
    "event_dead_letters_list",
    "event_migration_backfill",
    "event_migration_dry_run",
    "event_migration_shadow_compare",
    "event_projection_status",
    "event_quarantine_list",
    "event_quarantine_show",
    "event_replay_report_show",
    "event_replay_reports_list",
    "register",
]
