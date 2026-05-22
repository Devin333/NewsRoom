from __future__ import annotations

import argparse
import json

from interfaces.cli.commands.dispatch import CommandHandler, call_handler
from interfaces.services.memory_service import DEFAULT_MEMORY_COLLECTION


def register(subparsers: argparse._SubParsersAction) -> None:
    memory_parser = subparsers.add_parser("memory", help="Search and manage memory")
    memory_subparsers = memory_parser.add_subparsers(dest="memory_command", required=True)

    search_parser = memory_subparsers.add_parser("search", help="Search vector memory")
    search_parser.add_argument("query", help="Search query text")
    search_parser.add_argument(
        "--collection",
        default=DEFAULT_MEMORY_COLLECTION,
        help="Vector memory collection",
    )
    search_parser.add_argument("--limit", type=int, default=5, help="Maximum results")
    search_parser.add_argument(
        "--filter",
        dest="filters",
        action="append",
        default=[],
        help="Exact-match payload filter as key=value; can be repeated",
    )
    search_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    search_parser.set_defaults(handler=search_memory)

    reindex_parser = memory_subparsers.add_parser(
        "reindex",
        help="Rebuild vector memory from persisted run artifacts",
    )
    reindex_parser.add_argument("--run-id", required=True, help="Run id to reindex")
    reindex_parser.add_argument("--topic", default=None, help="Override memory topic")
    reindex_parser.add_argument(
        "--artifact-root",
        default=".newsroom/runs",
        help="Directory where run artifacts are stored",
    )
    reindex_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    reindex_parser.set_defaults(handler=reindex_memory)

    bootstrap_parser = memory_subparsers.add_parser(
        "bootstrap",
        help="Create expected Qdrant vector memory collections",
    )
    bootstrap_parser.add_argument(
        "--collection",
        dest="collections",
        action="append",
        default=[],
        help="Collection to bootstrap; repeat to override defaults",
    )
    bootstrap_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    bootstrap_parser.set_defaults(handler=bootstrap_memory)


def search_memory(args: argparse.Namespace) -> int:
    filters = parse_filters(args.filters)
    try:
        result = _memory_service().search(
            text=args.query,
            collection=args.collection,
            limit=args.limit,
            filters=filters,
        )
    except ModuleNotFoundError as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()

    if args.json:
        _print_json(payload)
    else:
        print(f"collection={payload['collection']}")
        print(f"query={payload['query']}")
        print(f"result_count={payload['result_count']}")
        for item in payload["results"]:
            print(f"- {item['document_id']} score={item['score']:.4f} source_type={item['source_type']}")
            if item.get("text"):
                print(f"  {item['text'][:160]}")
    return 0


def reindex_memory(args: argparse.Namespace) -> int:
    try:
        result = _memory_service(artifact_root=args.artifact_root).reindex_run(
            args.run_id,
            topic=args.topic,
        )
    except (FileNotFoundError, ValueError, ModuleNotFoundError) as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()
    if args.json:
        _print_json(payload)
    else:
        print(f"run_id={payload['run_id']}")
        print(f"topic={payload['topic']}")
        print(f"documents_indexed={payload['documents_indexed']}")
        print(f"collections={','.join(payload['collections'])}")
    return 0


def bootstrap_memory(args: argparse.Namespace) -> int:
    try:
        result = _memory_service().bootstrap_collections(
            collections=args.collections or None,
        )
    except (ValueError, ModuleNotFoundError) as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()
    if args.json:
        _print_json(payload)
    else:
        print(f"collection_count={payload['collection_count']}")
        print(f"created_count={payload['created_count']}")
        print(f"existing_count={payload['existing_count']}")
        for item in payload["collections"]:
            state = "created" if item["created"] else "existing"
            print(f"- {item['collection']} {state} vector_size={item['vector_size']}")
    return 0


def parse_filters(values: list[str]) -> dict[str, str]:
    filters: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"invalid filter '{value}', expected key=value")
        key, filter_value = value.split("=", 1)
        if not key:
            raise SystemExit(f"invalid filter '{value}', expected key=value")
        filters[key] = filter_value
    return filters


def _memory_service(*args, **kwargs):
    from interfaces.cli import news as news_cli

    return news_cli.MemoryApplicationService(*args, **kwargs)


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


add_memory_commands = register


__all__ = [
    "CommandHandler",
    "add_memory_commands",
    "bootstrap_memory",
    "call_handler",
    "parse_filters",
    "register",
    "reindex_memory",
    "search_memory",
]
