from __future__ import annotations

import argparse

from interfaces.cli.commands._legacy_mount import register_legacy_command


def register(subparsers: argparse._SubParsersAction) -> None:
    register_legacy_command(subparsers, "entities")


add_entities_commands = register


__all__ = ["add_entities_commands", "register"]
