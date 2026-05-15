from __future__ import annotations

import argparse
import glob
import os
import subprocess
import sys
from collections.abc import Sequence


COMPILE_PATHS = [
    "core",
    "domain",
    "evidence",
    "interfaces",
    "quality",
    "sources",
    "storage",
    "workflows",
    "scripts",
]

SMOKE_TOPIC = "AI agents"


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    env = _command_env()

    if args.command == "compile":
        return _run(_compile_command(), env=env)
    if args.command == "test":
        return _run([sys.executable, "-m", "pytest", "-q"], env=env)
    if args.command == "test-workflows":
        return _run(
            [
                sys.executable,
                "-m",
                "pytest",
                *_workflow_test_paths(),
                "tests/workflows",
                "-q",
            ],
            env=env,
        )
    if args.command == "test-services":
        return _run([sys.executable, "-m", "pytest", "tests/interfaces/services", "-q"], env=env)
    if args.command == "smoke-test-no-llm":
        return _run(_smoke_test_no_llm_command(run_id=args.run_id), env=env)
    if args.command == "smoke-test-agent-loop":
        return _run(_smoke_test_agent_loop_command(run_id=args.run_id), env=env)
    if args.command == "smoke-live-offline":
        return _run(_smoke_live_offline_command(run_id=args.run_id), env=env)
    if args.command == "smoke-live":
        return _run(_smoke_live_command(fail_if_unready=args.fail_if_unready), env=env)
    if args.command == "sources-validate":
        return _run(_news_command("sources", "validate"), env=env)
    if args.command == "diagnose":
        return _run(_news_command("diagnose"), env=env)
    if args.command == "smoke":
        commands = [
            _compile_command(),
            _smoke_test_no_llm_command(),
            _smoke_test_agent_loop_command(),
            _smoke_live_offline_command(),
            _news_command("sources", "validate"),
        ]
        return _run_many(commands, env=env, keep_going=args.keep_going)

    parser.error(f"unknown command: {args.command}")
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.dev")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("compile", help="Compile project Python modules")
    subparsers.add_parser("test", help="Run the full pytest suite")
    subparsers.add_parser("test-workflows", help="Run workflow tests")
    subparsers.add_parser("test-services", help="Run interface service tests")
    subparsers.add_parser("sources-validate", help="Validate configured source registry")
    subparsers.add_parser("diagnose", help="Run local diagnostics")

    smoke_parser = subparsers.add_parser("smoke", help="Run fixed offline smoke commands")
    smoke_parser.add_argument("--keep-going", action="store_true", help="Run all commands even after a failure")

    no_llm_parser = subparsers.add_parser("smoke-test-no-llm", help="Run deterministic no-LLM smoke")
    no_llm_parser.add_argument("--run-id", default=None, help="Optional deterministic run id")

    agent_loop_parser = subparsers.add_parser("smoke-test-agent-loop", help="Run deterministic AgentLoop smoke")
    agent_loop_parser.add_argument("--run-id", default=None, help="Optional deterministic run id")

    live_offline_parser = subparsers.add_parser("smoke-live-offline", help="Run offline daily workflow smoke")
    live_offline_parser.add_argument("--run-id", default=None, help="Optional deterministic run id")

    live_parser = subparsers.add_parser("smoke-live", help="Run gated live smoke")
    live_parser.add_argument(
        "--fail-if-unready",
        action="store_true",
        help="Fail instead of returning skipped when live dependencies are not configured",
    )

    return parser


def _compile_command() -> list[str]:
    return [sys.executable, "-m", "compileall", "-q", *COMPILE_PATHS]


def _workflow_test_paths() -> list[str]:
    paths = sorted(
        [
            *glob.glob("tests/core/framework/workflow/test_workflow_compiler_*.py"),
            *glob.glob("tests/core/framework/workflow/test_scheduler_*.py"),
            "tests/core/framework/workflow/test_workflow_state_machine.py",
            "tests/core/framework/workflow/test_step_state_machine.py",
        ]
    )
    return paths or [
        "tests/core/framework/workflow/test_workflow_compiler_*.py",
        "tests/core/framework/workflow/test_scheduler_*.py",
        "tests/core/framework/workflow/test_workflow_state_machine.py",
        "tests/core/framework/workflow/test_step_state_machine.py",
    ]


def _smoke_test_no_llm_command(run_id: str | None = None) -> list[str]:
    command = _news_command(
        "dev",
        "run-test-no-llm",
        "--topic",
        SMOKE_TOPIC,
    )
    if run_id:
        command.extend(["--run-id", run_id])
    return command


def _smoke_test_agent_loop_command(run_id: str | None = None) -> list[str]:
    command = _news_command(
        "dev",
        "run-test-agent-loop",
        "--topic",
        SMOKE_TOPIC,
    )
    if run_id:
        command.extend(["--run-id", run_id])
    return command


def _smoke_live_offline_command(run_id: str | None = None) -> list[str]:
    command = _news_command(
        "run",
        "daily",
        "--profile",
        "live-offline",
        "--topic",
        SMOKE_TOPIC,
        "--source-limit",
        "2",
    )
    if run_id:
        command.extend(["--run-id", run_id])
    return command


def _smoke_live_command(*, fail_if_unready: bool) -> list[str]:
    command = _news_command(
        "dev",
        "run-live-smoke",
        "--topic",
        SMOKE_TOPIC,
        "--source-limit",
        "3",
    )
    if fail_if_unready:
        command.append("--fail-if-unready")
    return command


def _news_command(*args: str) -> list[str]:
    return [sys.executable, "-m", "interfaces.cli.news", *args]


def _run_many(commands: Sequence[Sequence[str]], *, env: dict[str, str], keep_going: bool) -> int:
    exit_code = 0
    for command in commands:
        result = _run(command, env=env)
        if result != 0:
            exit_code = result
            if not keep_going:
                return result
    return exit_code


def _run(command: Sequence[str], *, env: dict[str, str]) -> int:
    print(f"+ {_format_command(command)}", flush=True)
    completed = subprocess.run(list(command), env=env, check=False)
    return int(completed.returncode)


def _format_command(command: Sequence[str]) -> str:
    return " ".join(_quote(part) for part in command)


def _quote(part: str) -> str:
    if not part:
        return '""'
    if any(char.isspace() for char in part):
        return '"' + part.replace('"', '\\"') + '"'
    return part


def _command_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


if __name__ == "__main__":
    raise SystemExit(main())
