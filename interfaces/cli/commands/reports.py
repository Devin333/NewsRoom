from __future__ import annotations

import argparse
import json
from typing import Any, Protocol

from interfaces.services.report_service import ReportApplicationService


class ReportServiceFactory(Protocol):
    def __call__(self, *, artifact_root: str) -> Any:
        ...


def register(subparsers: argparse._SubParsersAction) -> None:
    latest_parser = subparsers.add_parser("latest", help="Show latest local report")
    _add_latest_report_arguments(latest_parser)
    latest_parser.set_defaults(handler=latest_report_from_cli)

    reports_parser = subparsers.add_parser("reports", help="Inspect persisted reports")
    reports_subparsers = reports_parser.add_subparsers(dest="reports_command", required=True)

    reports_list_parser = reports_subparsers.add_parser("list", help="List persisted reports")
    reports_list_parser.add_argument("--limit", type=int, default=20, help="Maximum reports")
    reports_list_parser.add_argument("--graph-id", default=None, help="Optional Graph id filter")
    reports_list_parser.add_argument(
        "--graph-ids",
        nargs="+",
        default=None,
        help="Optional Graph id filters",
    )
    _add_artifact_root_argument(reports_list_parser)
    reports_list_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    reports_list_parser.set_defaults(handler=list_reports_from_cli)

    reports_show_parser = reports_subparsers.add_parser("show", help="Show one persisted report")
    reports_show_parser.add_argument("report_id", help="Report id")
    _add_artifact_root_argument(reports_show_parser)
    reports_show_parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format",
    )
    reports_show_parser.set_defaults(handler=show_report_from_cli)

    reports_search_parser = reports_subparsers.add_parser("search", help="Search persisted reports")
    reports_search_parser.add_argument("query", help="Search query")
    reports_search_parser.add_argument("--limit", type=int, default=20, help="Maximum reports")
    _add_artifact_root_argument(reports_search_parser)
    reports_search_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    reports_search_parser.set_defaults(handler=search_reports_from_cli)

    reports_latest_parser = reports_subparsers.add_parser("latest", help="Show latest persisted report")
    _add_latest_report_arguments(reports_latest_parser)
    reports_latest_parser.set_defaults(handler=latest_report_from_cli)


add_reports_commands = register


def latest_report_from_cli(args: argparse.Namespace) -> int:
    return latest_report(args, report_service_factory=ReportApplicationService)


def search_reports_from_cli(args: argparse.Namespace) -> int:
    return search_reports(args, report_service_factory=ReportApplicationService)


def list_reports_from_cli(args: argparse.Namespace) -> int:
    return list_reports(args, report_service_factory=ReportApplicationService)


def show_report_from_cli(args: argparse.Namespace) -> int:
    return show_report(args, report_service_factory=ReportApplicationService)


def _add_latest_report_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format",
    )
    _add_artifact_root_argument(parser)


def _add_artifact_root_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--artifact-root",
        default=".newsroom/runs",
        help="Directory where run artifacts are stored",
    )


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
            graph_id=args.graph_id,
            graph_ids=tuple(args.graph_ids) if args.graph_ids is not None else None,
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
                f"- {report['run_id']} graph={report.get('graph_id')}@{report.get('graph_version')} "
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
    "latest_report_from_cli",
    "list_reports",
    "list_reports_from_cli",
    "register",
    "search_reports",
    "search_reports_from_cli",
    "show_report",
    "show_report_from_cli",
]
