from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from typing import Any

from infrastructure.storage.lifecycle import RetentionPolicy
from interfaces.cli.commands.dispatch import CommandHandler, call_handler
from interfaces.services.storage_service import StorageApplicationService


def register(subparsers: argparse._SubParsersAction) -> None:
    storage_parser = subparsers.add_parser("storage", help="Inspect local storage")
    storage_subparsers = storage_parser.add_subparsers(dest="storage_command", required=True)

    metrics_parser = storage_subparsers.add_parser("metrics", help="Show local storage metrics")
    _add_artifact_root_argument(metrics_parser, help_text="Directory where run artifacts are stored")
    metrics_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    metrics_parser.set_defaults(handler=storage_metrics)

    migrate_parser = storage_subparsers.add_parser(
        "migrate",
        help="Run configured persistence migrations",
    )
    _add_artifact_root_argument(migrate_parser, help_text="Directory where local fallback records are stored")
    migrate_parser.add_argument(
        "--require-postgres",
        action="store_true",
        help="Fail if NEWS_DATABASE_DSN is not configured",
    )
    migrate_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    migrate_parser.set_defaults(handler=storage_migrate)

    backup_parser = storage_subparsers.add_parser(
        "backup",
        help="Create and restore local artifact backups",
    )
    backup_subparsers = backup_parser.add_subparsers(dest="storage_backup_command", required=True)

    backup_create_parser = backup_subparsers.add_parser(
        "create",
        help="Create a local artifact backup",
    )
    _add_storage_backup_arguments(backup_create_parser)
    backup_create_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing backup archive",
    )
    backup_create_parser.add_argument("--now", default=None, help="Optional current time as ISO datetime")
    backup_create_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    backup_create_parser.set_defaults(handler=storage_backup_create)

    backup_restore_parser = backup_subparsers.add_parser(
        "restore",
        help="Restore a local artifact backup",
    )
    _add_storage_backup_arguments(backup_restore_parser)
    backup_restore_parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm writing backed-up files",
    )
    backup_restore_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing restored files",
    )
    backup_restore_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    backup_restore_parser.set_defaults(handler=storage_backup_restore)

    lineage_parser = storage_subparsers.add_parser(
        "lineage",
        help="Query local lineage records",
    )
    lineage_subparsers = lineage_parser.add_subparsers(dest="storage_lineage_command", required=True)

    lineage_list_parser = lineage_subparsers.add_parser("list", help="List lineage refs for a run")
    _add_storage_lineage_base_arguments(lineage_list_parser)
    lineage_list_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    lineage_list_parser.set_defaults(handler=storage_lineage_list)

    lineage_upstream_parser = lineage_subparsers.add_parser(
        "upstream",
        help="List upstream lineage refs for a target",
    )
    _add_storage_lineage_base_arguments(lineage_upstream_parser)
    lineage_upstream_parser.add_argument("--target-type", required=True, help="Target record type")
    lineage_upstream_parser.add_argument("--target-id", required=True, help="Target record id")
    lineage_upstream_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    lineage_upstream_parser.set_defaults(handler=storage_lineage_upstream)

    lineage_downstream_parser = lineage_subparsers.add_parser(
        "downstream",
        help="List downstream lineage refs for a source",
    )
    _add_storage_lineage_base_arguments(lineage_downstream_parser)
    lineage_downstream_parser.add_argument("--source-type", required=True, help="Source record type")
    lineage_downstream_parser.add_argument("--source-id", required=True, help="Source record id")
    lineage_downstream_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    lineage_downstream_parser.set_defaults(handler=storage_lineage_downstream)

    retention_parser = storage_subparsers.add_parser(
        "retention",
        help="Plan and apply local artifact retention",
    )
    retention_subparsers = retention_parser.add_subparsers(dest="storage_retention_command", required=True)

    retention_plan_parser = retention_subparsers.add_parser("plan", help="Plan local artifact retention")
    _add_storage_retention_arguments(retention_plan_parser)
    retention_plan_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    retention_plan_parser.set_defaults(handler=storage_retention_plan)

    retention_apply_parser = retention_subparsers.add_parser("apply", help="Delete expired local artifacts")
    _add_storage_retention_arguments(retention_apply_parser)
    retention_apply_parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm deletion of expired artifacts",
    )
    retention_apply_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    retention_apply_parser.set_defaults(handler=storage_retention_apply)


def storage_metrics(args: argparse.Namespace) -> int:
    payload = _storage_service(args.artifact_root).metrics().to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"runs_count={payload['runs_count']}")
        print(f"reports_count={payload['reports_count']}")
        print(f"artifacts_count={payload['artifacts_count']}")
        print(f"artifact_bytes_total={payload['artifact_bytes_total']}")
        print(f"events_count={payload['events_count']}")
        print(f"lineage_refs_count={payload['lineage_refs_count']}")
    return 0


def storage_migrate(args: argparse.Namespace) -> int:
    try:
        result = _storage_service(args.artifact_root).migrate_persistence(
            require_postgres=args.require_postgres
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"migrated={str(payload['migrated']).lower()}")
        print(f"backend={payload['backend']}")
        print(f"postgres_required={str(payload['postgres_required']).lower()}")
    return 0


def storage_backup_create(args: argparse.Namespace) -> int:
    try:
        result = _storage_service(args.artifact_root).create_backup(
            args.backup_path,
            overwrite=args.overwrite,
            now=parse_cli_datetime(args.now),
        )
    except (FileNotFoundError, FileExistsError, ValueError) as exc:
        print(str(exc))
        return 1
    print_storage_backup_result(result.to_dict(), json_output=args.json, count_key="file_count")
    return 0


def storage_backup_restore(args: argparse.Namespace) -> int:
    if not args.yes:
        print("backup restore requires --yes")
        return 1
    try:
        result = _storage_service(args.artifact_root).restore_backup(
            args.backup_path,
            overwrite=args.overwrite,
        )
    except (FileNotFoundError, FileExistsError, ValueError) as exc:
        print(str(exc))
        return 1
    print_storage_backup_result(result.to_dict(), json_output=args.json, count_key="restored_count")
    return 0


def print_storage_backup_result(
    payload: dict,
    *,
    json_output: bool,
    count_key: str,
) -> None:
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return
    print(f"artifact_root={payload['artifact_root']}")
    print(f"backup_path={payload['backup_path']}")
    print(f"{count_key}={payload[count_key]}")
    print(f"total_bytes={payload['total_bytes']}")


def storage_lineage_list(args: argparse.Namespace) -> int:
    try:
        result = _storage_service(args.artifact_root).list_lineage(args.run_id)
    except ValueError as exc:
        print(str(exc))
        return 1
    print_storage_lineage_result(result.to_dict(), json_output=args.json)
    return 0


def storage_lineage_upstream(args: argparse.Namespace) -> int:
    try:
        result = _storage_service(args.artifact_root).lineage_upstream(
            run_id=args.run_id,
            target_type=args.target_type,
            target_id=args.target_id,
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    print_storage_lineage_result(result.to_dict(), json_output=args.json)
    return 0


def storage_lineage_downstream(args: argparse.Namespace) -> int:
    try:
        result = _storage_service(args.artifact_root).lineage_downstream(
            run_id=args.run_id,
            source_type=args.source_type,
            source_id=args.source_id,
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    print_storage_lineage_result(result.to_dict(), json_output=args.json)
    return 0


def print_storage_lineage_result(payload: dict, *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return
    print(f"artifact_root={payload['artifact_root']}")
    print(f"run_id={payload['run_id']}")
    print(f"query_type={payload['query_type']}")
    print(f"lineage_count={payload['lineage_count']}")
    for ref in payload["lineage_refs"]:
        print(
            f"- {ref['source_type']}:{ref['source_id']} -> "
            f"{ref['target_type']}:{ref['target_id']} relation={ref['relation_type']}"
        )


def storage_retention_plan(args: argparse.Namespace) -> int:
    try:
        result = _storage_service(args.artifact_root).plan_retention(
            policy=retention_policy_from_args(args),
            run_id=args.run_id,
            now=parse_cli_datetime(args.now),
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    print_storage_retention_result(result.to_dict(), json_output=args.json)
    return 0


def storage_retention_apply(args: argparse.Namespace) -> int:
    if not args.yes:
        print("retention apply requires --yes")
        return 1
    try:
        result = _storage_service(args.artifact_root).apply_retention(
            policy=retention_policy_from_args(args),
            run_id=args.run_id,
            now=parse_cli_datetime(args.now),
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print_storage_retention_result(payload, json_output=False)
        print(f"deleted_count={payload['deleted_count']}")
    return 0


def print_storage_retention_result(payload: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return
    print(f"artifact_root={payload['artifact_root']}")
    if payload["run_id"]:
        print(f"run_id={payload['run_id']}")
    print(f"artifact_count={payload['artifact_count']}")
    print(f"delete_count={payload['delete_count']}")
    print(f"keep_count={payload['keep_count']}")


def retention_policy_from_args(args: argparse.Namespace):
    payload = {}
    for name in [
        "raw_source_retention_days",
        "llm_artifact_retention_days",
        "run_artifact_retention_days",
        "report_retention_days",
        "evidence_retention_days",
        "vector_retention_days",
    ]:
        value = getattr(args, name)
        if value is not None:
            payload[name] = value
    return RetentionPolicy.from_dict(payload)


def parse_cli_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError as exc:
        raise SystemExit(f"invalid ISO datetime: {value}") from exc


def _storage_service(artifact_root: str):
    return StorageApplicationService(artifact_root)


def _add_artifact_root_argument(parser: argparse.ArgumentParser, *, help_text: str) -> None:
    parser.add_argument(
        "--artifact-root",
        default=".newsroom/runs",
        help=help_text,
    )


def _add_storage_backup_arguments(parser: argparse.ArgumentParser) -> None:
    _add_artifact_root_argument(parser, help_text="Directory where run artifacts are stored")
    parser.add_argument("--backup-path", required=True, help="Backup archive path")


def _add_storage_lineage_base_arguments(parser: argparse.ArgumentParser) -> None:
    _add_artifact_root_argument(parser, help_text="Directory where run artifacts are stored")
    parser.add_argument("--run-id", required=True, help="Workflow run id")


def _add_storage_retention_arguments(parser: argparse.ArgumentParser) -> None:
    _add_artifact_root_argument(parser, help_text="Directory where run artifacts are stored")
    parser.add_argument("--run-id", default=None, help="Optional run id filter")
    parser.add_argument("--now", default=None, help="Optional current time as ISO datetime")
    parser.add_argument("--raw-source-retention-days", type=int, default=None)
    parser.add_argument("--llm-artifact-retention-days", type=int, default=None)
    parser.add_argument("--run-artifact-retention-days", type=int, default=None)
    parser.add_argument("--report-retention-days", type=int, default=None)
    parser.add_argument("--evidence-retention-days", type=int, default=None)
    parser.add_argument("--vector-retention-days", type=int, default=None)


add_storage_commands = register


__all__ = [
    "CommandHandler",
    "add_storage_commands",
    "call_handler",
    "parse_cli_datetime",
    "print_storage_backup_result",
    "print_storage_lineage_result",
    "print_storage_retention_result",
    "register",
    "retention_policy_from_args",
    "storage_backup_create",
    "storage_backup_restore",
    "storage_lineage_downstream",
    "storage_lineage_list",
    "storage_lineage_upstream",
    "storage_metrics",
    "storage_migrate",
    "storage_retention_apply",
    "storage_retention_plan",
]
