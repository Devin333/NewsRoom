from __future__ import annotations

import argparse

from interfaces.cli import news
from interfaces.cli.news import build_parser, main


CORE_COMMANDS = {
    "api",
    "reports",
    "subscriptions",
    "entities",
    "workers",
    "memory",
    "sources",
    "mcp",
    "diagnose",
    "storage",
    "artifacts",
    "tools",
    "runs",
}


def test_news_entrypoint_exports_parser_and_main() -> None:
    assert callable(build_parser)
    assert callable(main)


def test_build_parser_registers_core_commands() -> None:
    parser = build_parser()

    assert isinstance(parser, argparse.ArgumentParser)
    assert CORE_COMMANDS.issubset(_top_level_commands(parser))


def test_command_modules_register_with_parser() -> None:
    assert news.COMMAND_MODULES
    for command_module in news.COMMAND_MODULES:
        assert callable(getattr(command_module, "register", None))


def test_news_public_api_is_entrypoint_only() -> None:
    assert set(news.__all__) == {
        "COMMAND_MODULES",
        "build_parser",
        "main",
        "print_json",
    }
    assert not any(name.endswith("ApplicationService") for name in news.__all__)
    assert "WorkflowStatus" not in news.__all__
    assert "RetentionPolicy" not in news.__all__


def _top_level_commands(parser: argparse.ArgumentParser) -> set[str]:
    for action in parser._actions:
        choices = getattr(action, "choices", None)
        if isinstance(choices, dict):
            return set(choices)
    return set()
