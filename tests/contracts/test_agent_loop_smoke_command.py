from __future__ import annotations

import sys
from pathlib import Path

import scripts.dev as dev


def test_agent_loop_smoke_dev_command_targets_graph_cli() -> None:
    args = dev.build_parser().parse_args(
        [
            "smoke-test-agent-loop",
            "--topic",
            "graph-only",
            "--artifact-root",
            "smoke-root",
            "--run-id",
            "run-1",
        ]
    )

    assert dev._agent_loop_smoke_command(args) == [
        sys.executable,
        "-m",
        "interfaces.cli.news",
        "dev",
        "run-test-agent-loop",
        "--topic",
        "graph-only",
        "--artifact-root",
        "smoke-root",
        "--json",
        "--run-id",
        "run-1",
    ]


def test_make_target_keeps_agent_loop_smoke_entrypoint() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "smoke-test-agent-loop:" in makefile
    assert "-m scripts.dev smoke-test-agent-loop" in makefile
