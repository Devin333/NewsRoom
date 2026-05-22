from __future__ import annotations

import argparse
from functools import lru_cache

from interfaces.cli import _legacy_news


def register_legacy_command(
    subparsers: argparse._SubParsersAction,
    command_name: str,
    *,
    alias: str | None = None,
) -> None:
    legacy_parser = _legacy_command_parser(command_name)
    help_text = _legacy_command_help(command_name)
    registered_name = alias or command_name
    subparsers.add_parser(registered_name, help=help_text)
    subparsers.choices[registered_name] = legacy_parser


@lru_cache(maxsize=1)
def _legacy_root_parser() -> argparse.ArgumentParser:
    return _legacy_news.build_parser()


def _legacy_subparsers() -> argparse._SubParsersAction:
    for action in _legacy_root_parser()._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    raise RuntimeError("legacy news parser has no subparsers")


def _legacy_command_parser(command_name: str) -> argparse.ArgumentParser:
    try:
        return _legacy_subparsers().choices[command_name]
    except KeyError as exc:
        raise RuntimeError(f"legacy news parser has no command: {command_name}") from exc


def _legacy_command_help(command_name: str) -> str | None:
    for action in _legacy_subparsers()._choices_actions:
        if action.dest == command_name:
            return action.help
    return None
