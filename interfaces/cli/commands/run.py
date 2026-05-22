from __future__ import annotations

import argparse
import json

from business.boards.cross_board.profiles import DAILY_PROFILE_CHOICES
from framework.specs import WorkflowStatus
from interfaces.cli.commands.dispatch import CommandHandler, call_handler
from interfaces.services.run_service import RunApplicationService


def register(subparsers: argparse._SubParsersAction) -> None:
    run_parser = subparsers.add_parser("run", help="Run product workflows")
    run_subparsers = run_parser.add_subparsers(dest="run_command", required=True)

    daily_parser = run_subparsers.add_parser("daily", help="Run daily intelligence workflow")
    daily_parser.add_argument(
        "--profile",
        choices=DAILY_PROFILE_CHOICES,
        default="live",
        help="Execution profile",
    )
    daily_parser.add_argument("--topic", default="AI", help="Topic for the daily report")
    daily_parser.add_argument("--source-limit", type=int, default=3, help="Maximum source items")
    daily_parser.add_argument(
        "--artifact-root",
        default=".newsroom/runs",
        help="Directory where run artifacts are written",
    )
    daily_parser.add_argument("--run-id", default=None, help="Optional deterministic run id")
    daily_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    daily_parser.set_defaults(handler=run_daily)

    weekly_parser = run_subparsers.add_parser("weekly", help="Run weekly intelligence workflow")
    weekly_parser.add_argument("--language", choices=["en"], default="en", help="Report language")
    weekly_parser.add_argument("--topic", default=None, help="Optional topic filter")
    weekly_parser.add_argument("--source-limit", type=int, default=20, help="Maximum source daily reports")
    weekly_parser.add_argument("--period-start", default=None, help="Optional inclusive ISO start datetime")
    weekly_parser.add_argument("--period-end", default=None, help="Optional inclusive ISO end datetime")
    weekly_parser.add_argument(
        "--artifact-root",
        default=".newsroom/runs",
        help="Directory where run artifacts are written",
    )
    weekly_parser.add_argument("--run-id", default=None, help="Optional deterministic run id")
    weekly_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    weekly_parser.set_defaults(handler=run_weekly)


def run_daily(args: argparse.Namespace) -> int:
    service = RunApplicationService(artifact_root=args.artifact_root)
    result = service.run_daily(
        profile=args.profile,
        topic=args.topic,
        source_limit=args.source_limit,
        run_id=args.run_id,
    )

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))
    else:
        print(f"status={result.status.value}")
        print(f"run_id={result.run_id}")
        print(f"profile={args.profile}")
        print(f"artifact_dir={result.artifact_dir}")
        print(f"manifest={result.manifest_path}")
        print(f"events={result.events_path}")
        if result.error:
            print(f"error={result.error.get('message')}")

    return 0 if result.status == WorkflowStatus.SUCCEEDED else 1


def run_weekly(args: argparse.Namespace) -> int:
    service = RunApplicationService(artifact_root=args.artifact_root)
    try:
        result = service.run_weekly(
            language=args.language,
            topic=args.topic,
            source_limit=args.source_limit,
            period_start=args.period_start,
            period_end=args.period_end,
            run_id=args.run_id,
        )
    except ValueError as exc:
        print(str(exc))
        return 1

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))
    else:
        print(f"status={result.status.value}")
        print(f"run_id={result.run_id}")
        print("profile=weekly")
        print(f"artifact_dir={result.artifact_dir}")
        print(f"manifest={result.manifest_path}")
        print(f"events={result.events_path}")
        if result.error:
            print(f"error={result.error.get('message')}")

    return 0 if result.status == WorkflowStatus.SUCCEEDED else 1


add_run_commands = register


__all__ = [
    "CommandHandler",
    "add_run_commands",
    "call_handler",
    "register",
    "run_daily",
    "run_weekly",
]
