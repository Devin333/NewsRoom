from __future__ import annotations

import argparse
import json

from framework.harness.control_plane.errors import HarnessValidationError
from interfaces.composition.agent_loop_smoke import (
    build_agent_loop_graph_smoke_service,
)


def register(subparsers: argparse._SubParsersAction) -> None:
    dev_parser = subparsers.add_parser(
        "dev",
        help="Run deterministic development fixtures",
    )
    dev_subparsers = dev_parser.add_subparsers(
        dest="dev_command",
        required=True,
    )
    agent_loop_parser = dev_subparsers.add_parser(
        "run-test-agent-loop",
        help="Run the offline AgentLoop Graph smoke fixture",
    )
    agent_loop_parser.add_argument(
        "--topic",
        default="daily intelligence agent loop smoke",
    )
    agent_loop_parser.add_argument(
        "--artifact-root",
        default=".newsroom/smoke",
    )
    agent_loop_parser.add_argument("--run-id", default=None)
    agent_loop_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON",
    )
    agent_loop_parser.set_defaults(handler=run_test_agent_loop)


def run_test_agent_loop(args: argparse.Namespace) -> int:
    try:
        result = build_agent_loop_graph_smoke_service(
            artifact_root=args.artifact_root,
        ).run(
            topic=args.topic,
            run_id=args.run_id,
        )
    except HarnessValidationError as exc:
        payload = {
            "error": {
                "code": exc.code or "test_agent_loop_graph_failed",
                "message": str(exc),
                "details": dict(exc.details),
            }
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 1
    except Exception:
        payload = {
            "error": {
                "code": "test_agent_loop_graph_failed",
                "message": "test AgentLoop Graph execution failed",
            }
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 1

    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"status={payload['status']}")
        print(f"run_id={payload['run_id']}")
        print(f"graph_ref={payload['graph_ref']}")
        print(f"artifact_path={payload['artifact_path']}")
        print(f"llm_calls={payload['llm_calls']}")
        print(f"tool_calls={payload['tool_calls']}")
    return 0


__all__ = ["register", "run_test_agent_loop"]
