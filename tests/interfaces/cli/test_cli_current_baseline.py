from __future__ import annotations

import pytest

from interfaces.cli.news import build_parser


def test_current_cli_parser_can_be_built() -> None:
    parser = build_parser()

    assert parser.prog == "news"


@pytest.mark.parametrize(
    "argv",
    [
        ["runs", "list", "--help"],
        ["reports", "list", "--help"],
        ["latest", "--help"],
        ["mcp", "catalog", "--help"],
    ],
)
def test_current_cli_help_commands_are_registered(argv: list[str], capsys) -> None:
    parser = build_parser()

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(argv)

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "usage:" in captured.out
