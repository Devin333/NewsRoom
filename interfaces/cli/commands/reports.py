from __future__ import annotations

import argparse
import json
from typing import Any, Protocol

from interfaces.cli.commands._legacy_mount import register_legacy_command


class ReportServiceFactory(Protocol):
    def __call__(self, *, artifact_root: str) -> Any:
        ...


def register(subparsers: argparse._SubParsersAction) -> None:
    register_legacy_command(subparsers, "latest")
    register_legacy_command(subparsers, "reports")


add_reports_commands = register


def latest_report(
    args: argparse.Namespace,
    *,
    report_service_factory: ReportServiceFactory,
) -> int:
    service = report_service_factory(artifact_root=args.artifact_root)
    try:
        record = service.latest_report()
    except FileNotFoundError as exc:
        print(str(exc))
        return 1

    if args.format == "json":
        print(json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True))
    else:
        print(record.report_markdown or json.dumps(record.report_json, ensure_ascii=False, indent=2))
    return 0

def search_reports(
    args: argparse.Namespace,
    *,
    report_service_factory: ReportServiceFactory,
) -> int:
    try:
        result = report_service_factory(artifact_root=args.artifact_root).search_reports(
            query=args.query,
            limit=args.limit,
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"report_count={payload['report_count']}")
        for report in payload["reports"]:
            print(f"- {report['run_id']} title={report['title']} finished_at={report['finished_at']}")
    return 0


def list_reports(
    args: argparse.Namespace,
    *,
    report_service_factory: ReportServiceFactory,
) -> int:
    try:
        result = report_service_factory(artifact_root=args.artifact_root).list_reports(
            limit=args.limit,
            workflow_id=args.workflow_id,
            workflow_family=args.workflow_family,
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"report_count={payload['report_count']}")
        for report in payload["reports"]:
            print(
                f"- {report['run_id']} workflow={report.get('workflow_id')} "
                f"title={report['title']} finished_at={report['finished_at']}"
            )
    return 0


def show_report(
    args: argparse.Namespace,
    *,
    report_service_factory: ReportServiceFactory,
) -> int:
    try:
        record = report_service_factory(artifact_root=args.artifact_root).get_report(args.report_id)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc))
        return 1
    payload = record.to_dict()
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(record.report_markdown or json.dumps(record.report_json, ensure_ascii=False, indent=2))
    return 0


__all__ = [
    "ReportServiceFactory",
    "add_reports_commands",
    "latest_report",
    "list_reports",
    "register",
    "search_reports",
    "show_report",
]
