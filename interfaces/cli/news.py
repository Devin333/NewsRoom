from __future__ import annotations

import argparse
import json
from typing import Sequence

from core.framework.specs import WorkflowStatus
from interfaces.services.run_service import RunApplicationService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="news", description="NewsRoom command line interface")
    subparsers = parser.add_subparsers(dest="command", required=True)

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
    no_llm_parser.add_argument(
        "--artifact-root",
        default=".newsroom/runs",
        help="Directory where run artifacts are written",
    )
    no_llm_parser.add_argument("--run-id", default=None, help="Optional deterministic run id")
    no_llm_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    no_llm_parser.set_defaults(handler=_run_test_no_llm)

    agent_loop_parser = dev_subparsers.add_parser(
        "run-test-agent-loop",
        help="Run deterministic FakeLLM + fake tool AgentLoop smoke test",
    )
    agent_loop_parser.add_argument(
        "--topic",
        default="daily intelligence agent loop smoke",
        help="Topic to include in the deterministic AgentLoop test",
    )
    agent_loop_parser.add_argument(
        "--artifact-root",
        default=".newsroom/runs",
        help="Directory where run artifacts are written",
    )
    agent_loop_parser.add_argument("--run-id", default=None, help="Optional deterministic run id")
    agent_loop_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    agent_loop_parser.set_defaults(handler=_run_test_agent_loop)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


def _run_test_no_llm(args: argparse.Namespace) -> int:
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


def _run_test_agent_loop(args: argparse.Namespace) -> int:
    service = RunApplicationService(artifact_root=args.artifact_root)
    result = service.run_test_agent_loop(topic=args.topic, run_id=args.run_id)
    metrics = result.output.get("agent_loop_metrics", {})

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


if __name__ == "__main__":
    raise SystemExit(main())
