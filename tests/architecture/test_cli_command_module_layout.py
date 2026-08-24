from __future__ import annotations

import importlib


def test_cli_command_group_modules_exist() -> None:
    command_groups = {
        "api",
        "waits",
        "artifacts",
        "diagnose",
        "dev",
        "dispatch",
        "entities",
        "events",
        "mcp",
        "memory",
        "reports",
        "runs",
        "schedules",
        "sources",
        "storage",
        "subscriptions",
        "tools",
        "workers",
    }

    for group in command_groups:
        module = importlib.import_module(f"interfaces.cli.commands.{group}")
        assert module is not None


def test_cli_news_remains_public_facade() -> None:
    from interfaces.cli import news

    assert callable(news.build_parser)
    assert callable(news.main)
