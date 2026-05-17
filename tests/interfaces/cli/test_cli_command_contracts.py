from __future__ import annotations

import pytest

from interfaces.cli.news import build_parser


@pytest.mark.parametrize(
    "argv",
    [
        ["run", "daily", "--help"],
        ["reports", "list", "--help"],
        ["reports", "latest", "--help"],
        ["latest", "--help"],
        ["runs", "list", "--help"],
        ["runs", "show", "--help"],
        ["runs", "events", "--help"],
        ["runs", "artifacts", "--help"],
        ["runs", "diagnostics", "--help"],
        ["runs", "replay", "--help"],
        ["runs", "cancel", "--help"],
        ["runs", "rerun-from-step", "--help"],
        ["mcp", "catalog", "--help"],
        ["mcp", "manifest", "--help"],
        ["mcp", "tools", "list", "--help"],
        ["mcp", "tools", "call", "--help"],
        ["mcp", "resources", "read", "--help"],
        ["mcp", "prompts", "list", "--help"],
        ["mcp", "prompts", "get", "--help"],
    ],
)
def test_product_cli_help_contracts(argv) -> None:
    parser = build_parser()

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(argv)

    assert exc_info.value.code == 0
