from __future__ import annotations

import argparse
from typing import Any, Sequence

from business.boards.cross_board.profiles import DAILY_PROFILE_CHOICES
from interfaces.cli import _legacy_news as _legacy
from interfaces.cli.commands import (
    api,
    approvals,
    artifacts,
    dev,
    diagnose,
    entities,
    mcp,
    memory,
    reports,
    run,
    runs,
    schedules,
    sources,
    storage,
    subscriptions,
    tools,
    workers,
)


COMMAND_MODULES = (
    run,
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
    dev,
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
    _sync_legacy_dependencies()
    return args.handler(args)


def print_json(payload: Any) -> None:
    _legacy.print_json(payload)


def _sync_legacy_dependencies() -> None:
    for name in _LEGACY_COMPAT_NAMES:
        if name in globals():
            setattr(_legacy, name, globals()[name])


_LEGACY_COMPAT_NAMES = [
    name
    for name in dir(_legacy)
    if not name.startswith("_") and name not in {"build_parser", "main", "print_json"}
]

for _name in _LEGACY_COMPAT_NAMES:
    globals()[_name] = getattr(_legacy, _name)


__all__ = [
    "build_parser",
    "main",
    "print_json",
    *_LEGACY_COMPAT_NAMES,
]
