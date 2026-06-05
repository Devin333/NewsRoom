from __future__ import annotations

import argparse
import json
from typing import Any, Sequence

from interfaces.cli.commands import (
    api,
    approvals,
    artifacts,
    diagnose,
    entities,
    mcp,
    memory,
    reports,
    runs,
    schedules,
    sources,
    storage,
    subscriptions,
    tools,
    workers,
)


COMMAND_MODULES = (
    reports,
    subscriptions,
    entities,
    api,
    workers,
    schedules,
    approvals,
    memory,
    diagnose,
    storage,
    sources,
    runs,
    artifacts,
    tools,
    mcp,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="news", description="NewsRoom command line interface")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command_module in COMMAND_MODULES:
        command_module.register(subparsers)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


def print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


__all__ = [
    "COMMAND_MODULES",
    "build_parser",
    "main",
    "print_json",
]


if __name__ == "__main__":
    raise SystemExit(main())
