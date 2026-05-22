from __future__ import annotations

import argparse
import json

from interfaces.cli.commands.dispatch import CommandHandler, call_handler
from interfaces.services.source_service import SourceApplicationService


def register(subparsers: argparse._SubParsersAction) -> None:
    sources_parser = subparsers.add_parser("sources", help="Inspect source registry and health")
    sources_subparsers = sources_parser.add_subparsers(dest="sources_command", required=True)

    list_parser = sources_subparsers.add_parser("list", help="List registered sources")
    list_parser.add_argument("--include-disabled", action="store_true", help="Include disabled sources")
    list_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    list_parser.set_defaults(handler=list_sources)

    arxiv_parser = sources_subparsers.add_parser("arxiv", help="Fetch arXiv source items")
    arxiv_parser.add_argument("--query", required=True, help="arXiv search query")
    arxiv_parser.add_argument("--limit", type=int, default=5, help="Maximum paper entries")
    arxiv_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    arxiv_parser.set_defaults(handler=fetch_arxiv)

    github_parser = sources_subparsers.add_parser("github", help="Fetch GitHub release items")
    github_parser.add_argument("--repo", required=True, help="GitHub repository as owner/repo")
    github_parser.add_argument("--limit", type=int, default=5, help="Maximum releases")
    github_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    github_parser.set_defaults(handler=fetch_github)

    health_parser = sources_subparsers.add_parser("health", help="Show source health")
    health_parser.add_argument("--include-disabled", action="store_true", help="Include disabled sources")
    health_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    health_parser.set_defaults(handler=source_health)

    check_health_parser = sources_subparsers.add_parser(
        "check-health",
        help="Probe configured sources and update source health",
    )
    check_health_parser.add_argument("--source-id", default=None, help="Optional source id to check")
    check_health_parser.add_argument("--include-disabled", action="store_true", help="Include disabled sources")
    check_health_parser.add_argument("--limit", type=int, default=None, help="Maximum sources to check")
    check_health_parser.add_argument("--force", action="store_true", help="Probe even during cooldown")
    check_health_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    check_health_parser.set_defaults(handler=check_source_health)

    validate_parser = sources_subparsers.add_parser("validate", help="Validate source registry")
    validate_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    validate_parser.set_defaults(handler=validate_sources)


def list_sources(args: argparse.Namespace) -> int:
    result = _source_service().list_sources(enabled_only=not args.include_disabled)
    payload = result.to_dict()

    if args.json:
        _print_json(payload)
    else:
        print(f"source_count={payload['source_count']}")
        for source in payload["sources"]:
            print(
                f"- {source['source_id']} type={source['source_type']} "
                f"reliability={source['reliability']} enabled={str(source['enabled']).lower()}"
            )
            print(f"  {source['name']} <{source['url']}>")
    return 0


def fetch_arxiv(args: argparse.Namespace) -> int:
    try:
        result = _source_service().fetch_arxiv(query=args.query, limit=args.limit)
    except ValueError as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()

    if args.json:
        _print_json(payload)
    else:
        _print_source_fetch_result(payload)
    return 0 if payload["error_count"] == 0 else 1


def fetch_github(args: argparse.Namespace) -> int:
    try:
        result = _source_service().fetch_github_releases(
            repository=args.repo,
            limit=args.limit,
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()

    if args.json:
        _print_json(payload)
    else:
        _print_source_fetch_result(payload)
    return 0 if payload["error_count"] == 0 else 1


def source_health(args: argparse.Namespace) -> int:
    result = _source_service().source_health(enabled_only=not args.include_disabled)
    payload = result.to_dict()

    if args.json:
        _print_json(payload)
    else:
        print(f"source_count={payload['source_count']}")
        for item in payload["health"]:
            print(
                f"- {item['source_id']} status={item['status']} "
                f"failures={item['consecutive_failures']} "
                f"success_24h={item.get('success_count_24h', 0)} "
                f"failure_24h={item.get('failure_count_24h', 0)} "
                f"avg_latency_ms_24h={item.get('avg_latency_ms_24h')}"
            )
    return 0


def check_source_health(args: argparse.Namespace) -> int:
    try:
        result = _source_service().check_source_health(
            source_id=args.source_id,
            enabled_only=not args.include_disabled,
            limit=args.limit,
            force=args.force,
        )
    except (KeyError, ValueError) as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()

    if args.json:
        _print_json(payload)
    else:
        print(f"checked_count={payload['checked_count']}")
        print(f"succeeded_count={payload['succeeded_count']}")
        print(f"failed_count={payload['failed_count']}")
        print(f"skipped_count={payload['skipped_count']}")
        for entry in payload["entries"]:
            print(
                f"- {entry['source_id']} ok={str(entry['ok']).lower()} "
                f"status={entry['status']} skipped={str(entry['skipped']).lower()}"
            )
    return 0 if payload["failed_count"] == 0 else 1


def validate_sources(args: argparse.Namespace) -> int:
    result = _source_service().validate_sources()
    payload = result.to_dict()

    if args.json:
        _print_json(payload)
    else:
        print(f"is_valid={str(payload['is_valid']).lower()}")
        print(f"error_count={payload['error_count']}")
        print(f"warning_count={payload['warning_count']}")
        raw_issues = payload.get("issues")
        issues = raw_issues if isinstance(raw_issues, list) else []
        for issue in issues:
            print(
                f"- {issue['severity']} {issue['source_id']}.{issue['field']}: "
                f"{issue['message']}"
            )
    return 0 if payload["is_valid"] else 2


def _source_service():
    return SourceApplicationService()


def _print_source_fetch_result(payload: dict) -> None:
    print(f"item_count={payload['item_count']}")
    print(f"error_count={payload['error_count']}")
    for item in payload["items"]:
        print(f"- {item['title']} <{item['url']}>")
    for error in payload["errors"]:
        print(f"error={error['error_type']}: {error['error_message']}")


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


add_sources_commands = register


__all__ = [
    "CommandHandler",
    "add_sources_commands",
    "call_handler",
    "check_source_health",
    "fetch_arxiv",
    "fetch_github",
    "list_sources",
    "register",
    "source_health",
    "validate_sources",
]
