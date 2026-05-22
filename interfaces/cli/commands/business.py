from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Protocol

from interfaces.services.business_acceptance_service import BusinessAcceptanceService


class BusinessAcceptanceServiceFactory(Protocol):
    def __call__(self) -> Any:
        ...


def register(subparsers: argparse._SubParsersAction) -> None:
    business_parser = subparsers.add_parser("business", help="Run business runtime acceptance checks")
    business_subparsers = business_parser.add_subparsers(dest="business_command", required=True)

    acceptance_parser = business_subparsers.add_parser(
        "acceptance",
        help="Run offline business runtime acceptance",
    )
    selection = acceptance_parser.add_mutually_exclusive_group()
    selection.add_argument("--board", choices=["ai_news", "project_radar", "paper_radar", "community_pulse"])
    selection.add_argument("--all-boards", action="store_true")
    selection.add_argument("--cross-board", action="store_true")
    selection.add_argument("--weekly", action="store_true")
    selection.add_argument("--eval", action="store_true")
    acceptance_parser.add_argument(
        "--artifact-root",
        default=".newsroom/acceptance",
        help="Artifact root used by offline acceptance runs",
    )
    acceptance_parser.add_argument("--run-id", default=None, help="Optional acceptance run id")
    acceptance_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    acceptance_parser.set_defaults(handler=run_acceptance_from_cli)


add_business_commands = register


def run_acceptance_from_cli(args: argparse.Namespace) -> int:
    return run_acceptance(
        args,
        business_acceptance_service_factory=BusinessAcceptanceService,
        print_result=print_acceptance_result,
    )


def run_acceptance(
    args: argparse.Namespace,
    *,
    business_acceptance_service_factory: BusinessAcceptanceServiceFactory,
    print_result,
) -> int:
    service = business_acceptance_service_factory()
    artifact_root = Path(args.artifact_root)
    try:
        if args.board:
            result = service.run_board_acceptance(args.board, artifact_root=artifact_root, run_id=args.run_id)
        elif args.all_boards:
            result = service.run_all_board_acceptance(artifact_root=artifact_root, run_id_prefix=args.run_id)
        elif args.cross_board:
            result = service.run_cross_board_acceptance(artifact_root=artifact_root, run_id=args.run_id)
        elif args.weekly:
            result = service.run_weekly_acceptance(artifact_root=artifact_root, run_id=args.run_id)
        elif args.eval:
            result = service.run_eval_acceptance(artifact_root=artifact_root, run_id=args.run_id)
        else:
            result = service.run_full_acceptance(artifact_root=artifact_root, run_id=args.run_id)
    except ValueError as exc:
        print(str(exc))
        return 1
    print_result(result, args.json)
    return 0 if result.status == "passed" else 1


def print_acceptance_result(result: Any, json_output: bool) -> None:
    payload = result.to_dict()
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return
    summary = payload.get("summary") or {}
    print(f"status={payload['status']}")
    print(f"run_id={payload['run_id']}")
    print(f"artifact_root={payload['artifact_root']}")
    print(f"checks={summary.get('passed_count', 0)}/{summary.get('check_count', len(payload.get('checks') or []))}")
    failed = [check for check in payload.get("checks") or [] if not check.get("passed")]
    if failed:
        print("failed_checks:")
        for check in failed[:10]:
            print(f"- {check['check_id']}: {check['message']}")


__all__ = [
    "BusinessAcceptanceServiceFactory",
    "add_business_commands",
    "print_acceptance_result",
    "register",
    "run_acceptance",
    "run_acceptance_from_cli",
]
