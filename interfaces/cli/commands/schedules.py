from __future__ import annotations

import argparse

from interfaces.cli.commands._legacy_mount import register_legacy_command
from interfaces.cli.commands.dispatch import CommandHandler, call_handler


def register(subparsers: argparse._SubParsersAction) -> None:
    register_legacy_command(subparsers, "schedules")


add_schedules_commands = register


__all__ = ["CommandHandler", "add_schedules_commands", "call_handler", "register"]
