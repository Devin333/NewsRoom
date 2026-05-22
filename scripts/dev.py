from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from framework.workflow.operations import (
    LocalWorkflowRunOperationService,
    OperationActor,
)


COMPILE_PATHS = [
    "business",
    "framework",
    "infrastructure",
    "interfaces",
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
                "tests/framework/workflow",
                "tests/business/boards/cross_board/workflows",
                "-q",
            ],
            env=env,
        )
    if args.command == "test-workflow-runtime-contracts":
        return _run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/framework/workflow",
                "-q",
            ],
            env=env,
        )
    if args.command == "test-workflow-domain":
        return _run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/business/boards/cross_board/workflows",
                "-q",
            ],
            env=env,
        )
    if args.command == "test-services":
        return _run([sys.executable, "-m", "pytest", "tests/interfaces/services", "-q"], env=env)
    if args.command == "test-interfaces":
        return _run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/interfaces",
                "-q",
            ],
            env=env,
        )
    if args.command == "test-api":
        return _run([sys.executable, "-m", "pytest", "tests/interfaces/api", "-q"], env=env)
    if args.command == "test-cli":
        return _run([sys.executable, "-m", "pytest", "tests/interfaces/cli", "-q"], env=env)
    if args.command == "test-mcp":
        return _run([sys.executable, "-m", "pytest", "tests/interfaces/mcp", "-q"], env=env)
    if args.command == "test-sdk":
        return _run([sys.executable, "-m", "pytest", "tests/sdk", "-q"], env=env)
    if args.command == "test-prd-daily":
        return _run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/framework/agent",
                "tests/framework/llm/test_clients_cache_prompt_redaction.py",
                "tests/interfaces/services/test_run_service_agentic_daily.py",
                "tests/interfaces/services/test_run_service_live_smoke.py",
                "tests/interfaces/services/test_report_service.py",
                "tests/interfaces/services/test_entity_service.py",
                "tests/interfaces/services/test_mcp_application_service.py",
                "tests/interfaces/services/test_approval_workflow_resume_service.py",
                "tests/interfaces/api/test_http_api_foundation.py",
                "tests/interfaces/api/test_final_target_routes.py",
                "tests/interfaces/api/test_approval_api.py",
                "tests/interfaces/cli/test_news_cli.py",
                "tests/interfaces/cli/test_entity_commands.py",
                "tests/interfaces/cli/test_approval_commands.py",
                "tests/business/layers/relation/evidence/test_claim_verifier.py",
                "tests/business/layers/analysis/quality/test_citation_editor.py",
                "tests/business/layers/analysis/quality/test_support_scoring.py",
                "tests/business/boards/cross_board/workflows/daily_intelligence/test_daily_agent_contracts.py",
                "tests/business/boards/cross_board/workflows/daily_intelligence/test_daily_agent_registry.py",
                "tests/business/boards/cross_board/workflows/daily_intelligence/test_daily_agentic_runner_offline.py",
                "tests/business/boards/cross_board/workflows/daily_intelligence/test_daily_finalize_report_step.py",
                "tests/business/boards/cross_board/workflows/daily_intelligence/test_daily_current_baseline.py",
                "tests/business/boards/cross_board/workflows/test_daily_intelligence_runner.py",
                "tests/business/boards/cross_board/workflows/test_weekly_intelligence_runner.py",
                "tests/business/boards/cross_board/workflows/test_workflow_runner_contracts.py",
                "tests/infrastructure/storage/test_artifact_store.py",
                "tests/infrastructure/storage/test_backup_restore.py",
                "-q",
            ],
            env=env,
        )
    if args.command == "test-api-contracts":
        return _run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/interfaces/api/test_api_contracts.py",
                "tests/interfaces/api/test_openapi_contract.py",
                "-q",
            ],
            env=env,
        )
    if args.command == "export-openapi":
        return _run(_export_openapi_command(), env=env)
    if args.command == "web-check":
        return _run(_web_check_command(), env=env)
    if args.command == "interface-smoke":
        commands = [
            _compile_command(),
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/interfaces/api/test_api_current_baseline.py",
                "tests/interfaces/mcp/test_mcp_current_baseline.py",
                "-q",
            ],
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/interfaces/api/test_api_contracts.py",
                "tests/interfaces/api/test_openapi_contract.py",
                "-q",
            ],
            _export_openapi_command(),
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/interfaces/cli/test_cli_current_baseline.py",
                "-q",
            ],
            _mcp_smoke_command(),
            _api_smoke_command(),
            _web_check_command(),
        ]
        return _run_many(commands, env=env, keep_going=args.keep_going)
    if args.command == "smoke-test-no-llm":
        return _run(_smoke_test_no_llm_command(run_id=args.run_id), env=env)
    if args.command == "smoke-test-agent-loop":
        return _run(_smoke_test_agent_loop_command(run_id=args.run_id), env=env)
    if args.command == "smoke-live-offline":
        return _run(_smoke_live_offline_command(run_id=args.run_id), env=env)
    if args.command == "smoke-agentic-offline":
        return _run(_smoke_agentic_offline_command(run_id=args.run_id), env=env)
    if args.command == "smoke-live":
        return _run(_smoke_live_command(fail_if_unready=args.fail_if_unready), env=env)
    if args.command == "sources-validate":
        return _run(_news_command("sources", "validate"), env=env)
    if args.command == "diagnose":
        return _run(_news_command("diagnose"), env=env)
    if args.command == "run-cancel":
        return _run_operation(args, "cancel")
    if args.command == "run-rerun-from-step":
        return _run_operation(args, "rerun_from_step")
    if args.command == "run-resume-with-patch":
        return _run_operation(args, "resume_with_patch")
    if args.command == "run-skip-step":
        return _run_operation(args, "skip_step")
    if args.command == "run-mark-blocked-resolved":
        return _run_operation(args, "mark_blocked_resolved")
    if args.command == "smoke":
        commands = [
            _compile_command(),
            _smoke_test_no_llm_command(),
            _smoke_test_agent_loop_command(),
            _smoke_live_offline_command(),
            _smoke_agentic_offline_command(),
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
    subparsers.add_parser(
        "test-workflow-runtime-contracts",
        help="Run workflow runtime contract tests",
    )
    subparsers.add_parser("test-workflow-domain", help="Run workflow domain tests")
    subparsers.add_parser("test-services", help="Run interface service tests")
    subparsers.add_parser("test-interfaces", help="Run interface acceptance tests")
    subparsers.add_parser("test-api", help="Run HTTP API interface tests")
    subparsers.add_parser("test-cli", help="Run CLI interface tests")
    subparsers.add_parser("test-mcp", help="Run MCP interface tests")
    subparsers.add_parser("test-sdk", help="Run SDK tests")
    subparsers.add_parser("test-prd-daily", help="Run the PRD-aligned daily agentic regression sweep")
    subparsers.add_parser("export-openapi", help="Export docs/api/openapi.json")
    subparsers.add_parser("test-api-contracts", help="Run API contract tests")
    subparsers.add_parser("web-check", help="Check Web Console skeleton files")
    subparsers.add_parser("sources-validate", help="Validate configured source registry")
    subparsers.add_parser("diagnose", help="Run local diagnostics")

    interface_smoke_parser = subparsers.add_parser(
        "interface-smoke",
        help="Run interface-layer acceptance smoke commands",
    )
    interface_smoke_parser.add_argument(
        "--keep-going",
        action="store_true",
        help="Run all smoke commands even after a failure",
    )

    smoke_parser = subparsers.add_parser("smoke", help="Run fixed offline smoke commands")
    smoke_parser.add_argument("--keep-going", action="store_true", help="Run all commands even after a failure")

    no_llm_parser = subparsers.add_parser("smoke-test-no-llm", help="Run deterministic no-LLM smoke")
    no_llm_parser.add_argument("--run-id", default=None, help="Optional deterministic run id")

    agent_loop_parser = subparsers.add_parser("smoke-test-agent-loop", help="Run deterministic AgentLoop smoke")
    agent_loop_parser.add_argument("--run-id", default=None, help="Optional deterministic run id")

    live_offline_parser = subparsers.add_parser("smoke-live-offline", help="Run offline daily workflow smoke")
    live_offline_parser.add_argument("--run-id", default=None, help="Optional deterministic run id")

    agentic_offline_parser = subparsers.add_parser(
        "smoke-agentic-offline",
        help="Run deterministic agentic offline daily workflow smoke",
    )
    agentic_offline_parser.add_argument("--run-id", default=None, help="Optional deterministic run id")

    live_parser = subparsers.add_parser("smoke-live", help="Run gated live smoke")
    live_parser.add_argument(
        "--fail-if-unready",
        action="store_true",
        help="Fail instead of returning skipped when live dependencies are not configured",
    )

    _add_run_operation_parsers(subparsers)

    return parser


def _add_run_operation_parsers(subparsers: argparse._SubParsersAction) -> None:
    cancel_parser = subparsers.add_parser("run-cancel", help="Cancel a workflow run")
    _add_operation_base_args(cancel_parser)
    cancel_parser.add_argument("--reason", required=True)

    rerun_parser = subparsers.add_parser(
        "run-rerun-from-step",
        help="Rerun a workflow run from a step",
    )
    _add_operation_base_args(rerun_parser)
    rerun_parser.add_argument("--step-id", required=True)

    resume_parser = subparsers.add_parser(
        "run-resume-with-patch",
        help="Resume a workflow run with a JSON patch",
    )
    _add_operation_base_args(resume_parser)
    resume_parser.add_argument("--patch-json", required=True)

    skip_parser = subparsers.add_parser("run-skip-step", help="Skip a workflow step")
    _add_operation_base_args(skip_parser)
    skip_parser.add_argument("--step-id", required=True)
    skip_parser.add_argument("--reason", required=True)

    blocked_parser = subparsers.add_parser(
        "run-mark-blocked-resolved",
        help="Record that a blocked run has been externally resolved",
    )
    _add_operation_base_args(blocked_parser)
    blocked_parser.add_argument("--resolution-json", required=True)


def _add_operation_base_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--artifact-root", default="outputs/runs")
    parser.add_argument("--actor-id", default=None)


def _compile_command() -> list[str]:
    return [sys.executable, "-m", "compileall", "-q", *COMPILE_PATHS]


def _export_openapi_command() -> list[str]:
    return [sys.executable, "-m", "scripts.export_openapi"]


def _web_check_command() -> list[str]:
    return [sys.executable, "-m", "scripts.check_web_console"]


def _api_smoke_command() -> list[str]:
    return [sys.executable, "-m", "scripts.smoke.api_smoke"]


def _mcp_smoke_command() -> list[str]:
    return [sys.executable, "-m", "scripts.smoke.mcp_smoke"]


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


def _smoke_agentic_offline_command(run_id: str | None = None) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "scripts.smoke.agentic_daily_offline",
        "--topic",
        SMOKE_TOPIC,
        "--source-limit",
        "2",
    ]
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


def _run_operation(args: argparse.Namespace, operation: str) -> int:
    service = LocalWorkflowRunOperationService(artifact_root=args.artifact_root)
    actor = OperationActor(actor_id=args.actor_id) if args.actor_id else None
    if operation == "cancel":
        result = service.cancel_run(args.run_id, args.reason, actor=actor)
    elif operation == "rerun_from_step":
        result = service.rerun_from_step(args.run_id, args.step_id, actor=actor)
    elif operation == "resume_with_patch":
        result = service.resume_with_patch(
            args.run_id,
            _read_json_argument(args.patch_json),
            actor=actor,
        )
    elif operation == "skip_step":
        result = service.skip_step(
            args.run_id,
            args.step_id,
            args.reason,
            actor=actor,
        )
    elif operation == "mark_blocked_resolved":
        result = service.mark_blocked_resolved(
            args.run_id,
            _read_json_argument(args.resolution_json),
            actor=actor,
        )
    else:  # pragma: no cover - parser dispatch prevents this
        raise ValueError(f"unknown run operation: {operation}")
    print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))
    return 0 if result.status.value in {"accepted", "applied"} else 1


def _read_json_argument(value: str) -> dict:
    path = Path(value)
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        payload = json.loads(value)
    if not isinstance(payload, dict):
        raise ValueError("JSON argument must be an object")
    return payload


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
