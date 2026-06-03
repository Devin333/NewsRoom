from __future__ import annotations

import argparse
import json

from framework.specs import WorkflowStatus
from interfaces.cli.commands.dispatch import CommandHandler, call_handler
from interfaces.services.daily_interface_projection import (
    project_daily_agent_loop_metrics_for_interface,
)
from interfaces.services.run_service import RunApplicationService


def register(subparsers: argparse._SubParsersAction) -> None:
    dev_parser = subparsers.add_parser("dev", help="Development and regression commands")
    dev_subparsers = dev_parser.add_subparsers(dest="dev_command", required=True)

    no_llm_parser = dev_subparsers.add_parser(
        "run-test-no-llm",
        help="Run deterministic function-only workflow smoke test",
    )
    no_llm_parser.add_argument(
        "--topic",
        default="daily intelligence runtime smoke",
        help="Topic to include in the deterministic test report",
    )
    _add_run_artifact_arguments(no_llm_parser)
    no_llm_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    no_llm_parser.set_defaults(handler=run_test_no_llm)

    agent_loop_parser = dev_subparsers.add_parser(
        "run-test-agent-loop",
        help="Run deterministic FakeLLM + fake tool AgentLoop smoke test",
    )
    agent_loop_parser.add_argument(
        "--topic",
        default="daily intelligence agent loop smoke",
        help="Topic to include in the deterministic AgentLoop test",
    )
    _add_run_artifact_arguments(agent_loop_parser)
    agent_loop_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    agent_loop_parser.set_defaults(handler=run_test_agent_loop)

    live_smoke_parser = dev_subparsers.add_parser(
        "run-live-smoke",
        help="Run real live workflow smoke when live credentials are configured",
    )
    live_smoke_parser.add_argument("--topic", default="AI", help="Topic for the live smoke report")
    live_smoke_parser.add_argument("--source-limit", type=int, default=3, help="Maximum source items")
    _add_run_artifact_arguments(live_smoke_parser)
    live_smoke_parser.add_argument(
        "--fail-if-unready",
        action="store_true",
        help="Return failure instead of skipped when live readiness checks are not configured",
    )
    live_smoke_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    live_smoke_parser.set_defaults(handler=run_live_smoke)


def run_test_no_llm(args: argparse.Namespace) -> int:
    service = RunApplicationService(artifact_root=args.artifact_root)
    result = service.run_test_no_llm(topic=args.topic, run_id=args.run_id)

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))
    else:
        print(f"status={result.status.value}")
        print(f"run_id={result.run_id}")
        print(f"artifact_dir={result.artifact_dir}")
        print(f"manifest={result.manifest_path}")
        print(f"events={result.events_path}")

    return 0 if result.status == WorkflowStatus.SUCCEEDED else 1


def run_test_agent_loop(args: argparse.Namespace) -> int:
    service = RunApplicationService(artifact_root=args.artifact_root)
    result = service.run_test_agent_loop(topic=args.topic, run_id=args.run_id)
    metrics = project_daily_agent_loop_metrics_for_interface(result.output)

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))
    else:
        print(f"status={result.status.value}")
        print(f"run_id={result.run_id}")
        print(f"artifact_dir={result.artifact_dir}")
        print(f"manifest={result.manifest_path}")
        print(f"events={result.events_path}")
        print(f"llm_calls={metrics.get('llm_calls', 0)}")
        print(f"tool_calls={metrics.get('tool_calls', 0)}")

    return 0 if result.status == WorkflowStatus.SUCCEEDED else 1


def run_live_smoke(args: argparse.Namespace) -> int:
    service = RunApplicationService(artifact_root=args.artifact_root)
    result = service.run_live_smoke(
        topic=args.topic,
        source_limit=args.source_limit,
        run_id=args.run_id,
        skip_if_unready=not args.fail_if_unready,
    )

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))
    else:
        print(f"status={result.status}")
        print("profile=live")
        print(f"topic={args.topic}")
        print(f"source_limit={args.source_limit}")
        print(f"message={result.message}")
        if result.run_result:
            print(f"run_id={result.run_result.run_id}")
            print(f"artifact_dir={result.run_result.artifact_dir}")

    return 0 if result.status in {"succeeded", "skipped"} else 1


def _add_run_artifact_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--artifact-root",
        default=".newsroom/runs",
        help="Directory where run artifacts are written",
    )
    parser.add_argument("--run-id", default=None, help="Optional deterministic run id")


add_dev_commands = register


__all__ = [
    "CommandHandler",
    "add_dev_commands",
    "call_handler",
    "register",
    "run_live_smoke",
    "run_test_agent_loop",
    "run_test_no_llm",
]
