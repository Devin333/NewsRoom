from __future__ import annotations

import argparse

from interfaces.cli.news import build_parser


def test_cli_build_parser_and_top_level_commands_exist() -> None:
    parser = build_parser()
    action = _top_level_subparsers(parser)

    assert parser.prog == "news"
    for command in {
        "api",
        "latest",
        "reports",
        "subscriptions",
        "entities",
        "worker",
        "workers",
        "memory",
        "paper",
        "sources",
        "mcp",
        "diagnose",
        "storage",
        "approvals",
        "artifacts",
        "tools",
    }:
        assert command in action.choices


def test_cli_key_subcommands_and_handlers_are_bound() -> None:
    parser = build_parser()

    for argv in [
        ["api", "openapi"],
        ["runs", "list"],
        ["reports", "list"],
        ["reports", "show", "report-1"],
        ["subscriptions", "list"],
        ["entities", "list"],
        ["worker", "status"],
        ["workers", "status"],
        ["memory", "bootstrap"],
        ["paper", "ask", "1706.03762", "What is the method?", "--answer", "--legacy-direct-answer"],
        ["sources", "list"],
        ["mcp", "catalog"],
        ["storage", "metrics"],
        ["approvals", "list"],
        ["artifacts", "list", "--run-id", "run-1"],
    ]:
        args = parser.parse_args(argv)
        assert callable(args.handler)


def test_cli_paper_ask_registers_gated_answer_fallback_flag() -> None:
    args = build_parser().parse_args([
        "paper",
        "ask",
        "1706.03762",
        "What is the method?",
        "--answer",
        "--legacy-direct-answer",
    ])

    assert args.paper_command == "ask"
    assert args.answer is True
    assert args.legacy_direct_answer is True


def _top_level_subparsers(parser: argparse.ArgumentParser) -> argparse._SubParsersAction:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    raise AssertionError("parser has no subparsers")
