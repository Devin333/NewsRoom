from __future__ import annotations

import argparse
import json

from interfaces.cli.commands.dispatch import CommandHandler, call_handler
from interfaces.services.source_runtime import build_source_runtime_composition


def register(subparsers: argparse._SubParsersAction) -> None:
    sources_parser = subparsers.add_parser("sources", help="Inspect source registry and health")
    sources_subparsers = sources_parser.add_subparsers(dest="sources_command", required=True)

    list_parser = sources_subparsers.add_parser("list", help="List registered sources")
    list_parser.add_argument("--include-disabled", action="store_true", help="Include disabled sources")
    list_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    list_parser.set_defaults(handler=list_sources)

    inspect_parser = sources_subparsers.add_parser("inspect", help="Inspect one registered source")
    inspect_parser.add_argument("--source-id", required=True, help="Source id to inspect")
    inspect_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    inspect_parser.set_defaults(handler=inspect_source)

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

    fetch_parser = sources_subparsers.add_parser("fetch", help="Fetch one configured source")
    fetch_parser.add_argument("--source-id", required=True, help="Source id to fetch")
    fetch_parser.add_argument("--limit", type=int, default=10, help="Maximum items")
    fetch_parser.add_argument("--query", default=None, help="Optional connector query override")
    fetch_parser.add_argument("--force", action="store_true", help="Fetch even during cooldown or interval skip")
    fetch_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    fetch_parser.set_defaults(handler=fetch_source)

    fetch_category_parser = sources_subparsers.add_parser("fetch-category", help="Fetch configured sources by category")
    fetch_category_parser.add_argument("--category", required=True, help="Source category")
    fetch_category_parser.add_argument("--limit-per-source", type=int, default=5, help="Maximum items per source")
    fetch_category_parser.add_argument("--priority", default=None, help="Optional priority filter")
    fetch_category_parser.add_argument("--language", default=None, help="Optional language filter")
    fetch_category_parser.add_argument("--region", default=None, help="Optional region filter")
    fetch_category_parser.add_argument("--include-disabled", action="store_true", help="Include disabled sources")
    fetch_category_parser.add_argument("--force", action="store_true", help="Fetch even during cooldown or interval skip")
    fetch_category_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    fetch_category_parser.set_defaults(handler=fetch_category)

    fetch_priority_parser = sources_subparsers.add_parser("fetch-priority", help="Fetch configured sources by priority")
    fetch_priority_parser.add_argument("--priority", required=True, help="Source metadata priority")
    fetch_priority_parser.add_argument("--limit-per-source", type=int, default=5, help="Maximum items per source")
    fetch_priority_parser.add_argument("--include-disabled", action="store_true", help="Include disabled sources")
    fetch_priority_parser.add_argument("--force", action="store_true", help="Fetch even during cooldown or interval skip")
    fetch_priority_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    fetch_priority_parser.set_defaults(handler=fetch_priority)

    fetch_topic_parser = sources_subparsers.add_parser("fetch-topic", help="Fetch configured sources by topic")
    fetch_topic_parser.add_argument("--topic", required=True, help="Topic text for source selection")
    fetch_topic_parser.add_argument("--limit-per-source", type=int, default=5, help="Maximum items per source")
    fetch_topic_parser.add_argument("--category", default=None, help="Optional category filter")
    fetch_topic_parser.add_argument("--priority", default=None, help="Optional priority filter")
    fetch_topic_parser.add_argument("--language", default=None, help="Optional language filter")
    fetch_topic_parser.add_argument("--region", default=None, help="Optional region filter")
    fetch_topic_parser.add_argument("--include-disabled", action="store_true", help="Include disabled sources")
    fetch_topic_parser.add_argument("--force", action="store_true", help="Fetch even during cooldown or interval skip")
    fetch_topic_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    fetch_topic_parser.set_defaults(handler=fetch_topic)

    categories_parser = sources_subparsers.add_parser("categories", help="List supported source categories")
    categories_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    categories_parser.set_defaults(handler=source_categories)

    priorities_parser = sources_subparsers.add_parser("priorities", help="List supported source priorities")
    priorities_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    priorities_parser.set_defaults(handler=source_priorities)


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


def inspect_source(args: argparse.Namespace) -> int:
    try:
        result = _source_service().get_source(args.source_id)
    except (KeyError, ValueError) as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()

    if args.json:
        _print_json(payload)
    else:
        source = payload["source"]
        print(f"source_id={source['source_id']}")
        print(f"name={source['name']}")
        print(f"source_type={source['source_type']}")
        print(f"url={source['url']}")
        print(f"category={source.get('category')}")
        print(f"language={source.get('language')}")
        print(f"region={source.get('region')}")
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


def fetch_source(args: argparse.Namespace) -> int:
    try:
        result = _source_service().fetch_source(
            source_id=args.source_id,
            limit=args.limit,
            query=args.query,
            force=args.force,
        )
    except (KeyError, ValueError) as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()

    if args.json:
        _print_json(payload)
    else:
        _print_source_fetch_result(payload)
    return 0


def fetch_category(args: argparse.Namespace) -> int:
    try:
        result = _source_service().fetch_category(
            category=args.category,
            limit_per_source=args.limit_per_source,
            enabled_only=not args.include_disabled,
            priority=args.priority,
            language=args.language,
            region=args.region,
            force=args.force,
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()

    if args.json:
        _print_json(payload)
    else:
        _print_source_batch_result(payload)
    return 0


def fetch_priority(args: argparse.Namespace) -> int:
    try:
        result = _source_service().fetch_priority(
            priority=args.priority,
            limit_per_source=args.limit_per_source,
            enabled_only=not args.include_disabled,
            force=args.force,
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()

    if args.json:
        _print_json(payload)
    else:
        _print_source_batch_result(payload)
    return 0


def fetch_topic(args: argparse.Namespace) -> int:
    try:
        result = _source_service().fetch_topic_sources(
            topic=args.topic,
            limit_per_source=args.limit_per_source,
            enabled_only=not args.include_disabled,
            category=args.category,
            priority=args.priority,
            language=args.language,
            region=args.region,
            force=args.force,
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()

    if args.json:
        _print_json(payload)
    else:
        _print_source_batch_result(payload)
    return 0


def source_categories(args: argparse.Namespace) -> int:
    payload = _source_service().source_categories()
    if args.json:
        _print_json(payload)
    else:
        print(f"category_count={payload['category_count']}")
        for category in payload["categories"]:
            print(f"- {category}")
    return 0


def source_priorities(args: argparse.Namespace) -> int:
    payload = _source_service().source_priorities()
    if args.json:
        _print_json(payload)
    else:
        print(f"priority_count={payload['priority_count']}")
        for priority in payload["priorities"]:
            print(f"- {priority}")
    return 0


def _source_service():
    return build_source_runtime_composition().source_service


def _print_source_fetch_result(payload: dict) -> None:
    print(f"item_count={payload['item_count']}")
    print(f"error_count={payload['error_count']}")
    for item in payload["items"]:
        print(f"- {item['title']} <{item['url']}>")
    for error in payload["errors"]:
        print(f"error={error['error_type']}: {error['error_message']}")


def _print_source_batch_result(payload: dict) -> None:
    print(f"source_count={payload['source_count']}")
    print(f"item_count={payload['item_count']}")
    print(f"error_count={payload['error_count']}")
    print(f"skipped_count={payload['skipped_count']}")
    for result in payload["results"]:
        print(
            f"- {result['source_id']} type={result['source_type']} "
            f"items={result['item_count']} errors={result['error_count']}"
        )


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=True, sort_keys=True))


add_sources_commands = register


__all__ = [
    "CommandHandler",
    "add_sources_commands",
    "call_handler",
    "check_source_health",
    "fetch_arxiv",
    "fetch_category",
    "fetch_github",
    "fetch_priority",
    "fetch_source",
    "fetch_topic",
    "inspect_source",
    "list_sources",
    "register",
    "source_categories",
    "source_health",
    "source_priorities",
    "validate_sources",
]
