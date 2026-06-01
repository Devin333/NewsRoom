from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from typing import Any, Protocol

from business.boards.cross_board.profiles import DAILY_PROFILE_CHOICES
from interfaces.cli.commands.dispatch import CommandHandler, call_handler
from interfaces.services.schedule_service import DEFAULT_PAPER_QUEUE, DEFAULT_SCHEDULE_STORE_PATH, ScheduleApplicationService
from interfaces.services.worker_service import DEFAULT_DAILY_QUEUE


class ScheduleServiceFactory(Protocol):
    def __call__(
        self,
        *,
        store_path: str,
        redis_url: str | None = None,
    ) -> Any:
        ...


def register(subparsers: argparse._SubParsersAction) -> None:
    schedules_parser = subparsers.add_parser("schedules", help="Manage background schedules")
    schedules_subparsers = schedules_parser.add_subparsers(dest="schedules_command", required=True)

    list_parser = schedules_subparsers.add_parser("list", help="List schedules")
    list_parser.add_argument("--enabled-only", action="store_true", help="Only include enabled schedules")
    _add_store_path(list_parser)
    list_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    list_parser.set_defaults(handler=list_schedules_from_cli)

    add_daily_parser = schedules_subparsers.add_parser(
        "add-daily",
        help="Create or update a daily intelligence schedule",
    )
    add_daily_parser.add_argument("--schedule-id", default="daily-intelligence", help="Schedule id")
    add_daily_parser.add_argument("--name", default="Daily intelligence", help="Schedule name")
    add_daily_parser.add_argument(
        "--trigger-type",
        choices=["interval", "manual"],
        default="interval",
        help="Schedule trigger type",
    )
    add_daily_parser.add_argument(
        "--interval-seconds",
        type=int,
        default=86400,
        help="Interval in seconds for interval schedules",
    )
    add_daily_parser.add_argument("--run-at", default=None, help="Optional first due time as ISO datetime")
    add_daily_parser.add_argument(
        "--profile",
        choices=DAILY_PROFILE_CHOICES,
        default="live-offline",
        help="Execution profile",
    )
    add_daily_parser.add_argument("--topic", default="AI", help="Topic for the daily report")
    add_daily_parser.add_argument("--source-limit", type=int, default=3, help="Maximum source items")
    add_daily_parser.add_argument("--queue-name", default=DEFAULT_DAILY_QUEUE, help="Queue name")
    _add_store_path(add_daily_parser)
    add_daily_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    add_daily_parser.set_defaults(handler=add_daily_schedule_from_cli)

    add_paper_reader_backfill_parser = schedules_subparsers.add_parser(
        "add-paper-reader-backfill",
        help="Create or update a Paper Reader visual compile backfill schedule",
    )
    add_paper_reader_backfill_parser.add_argument(
        "--schedule-id",
        default="papers-visual-compile-backfill",
        help="Schedule id",
    )
    add_paper_reader_backfill_parser.add_argument(
        "--name",
        default="Paper Reader visual compile backfill",
        help="Schedule name",
    )
    add_paper_reader_backfill_parser.add_argument(
        "--trigger-type",
        choices=["interval", "manual"],
        default="interval",
        help="Schedule trigger type",
    )
    add_paper_reader_backfill_parser.add_argument(
        "--interval-seconds",
        type=int,
        default=21600,
        help="Interval in seconds for interval schedules",
    )
    add_paper_reader_backfill_parser.add_argument("--run-at", default=None, help="Optional first due time as ISO datetime")
    add_paper_reader_backfill_parser.add_argument("--limit", type=int, default=None, help="Maximum papers to enqueue per run")
    add_paper_reader_backfill_parser.add_argument("--force", action="store_true", help="Recompile papers even when already compiled")
    add_paper_reader_backfill_parser.add_argument("--queue-name", default=DEFAULT_PAPER_QUEUE, help="Queue name")
    _add_store_path(add_paper_reader_backfill_parser)
    add_paper_reader_backfill_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    add_paper_reader_backfill_parser.set_defaults(handler=add_paper_reader_backfill_schedule_from_cli)

    tick_parser = schedules_subparsers.add_parser("tick", help="Evaluate schedules and enqueue due tasks")
    _add_store_path(tick_parser)
    tick_parser.add_argument("--redis-url", default=None, help="Redis URL; defaults to NEWS_REDIS_URL")
    tick_parser.add_argument("--now", default=None, help="Optional current time as ISO datetime")
    tick_parser.add_argument(
        "--include-disabled",
        action="store_true",
        help="Evaluate disabled schedules too",
    )
    tick_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    tick_parser.set_defaults(handler=tick_schedules_from_cli)

    run_parser = schedules_subparsers.add_parser(
        "run",
        help="Continuously evaluate schedules and enqueue due tasks",
    )
    _add_store_path(run_parser)
    run_parser.add_argument("--redis-url", default=None, help="Redis URL; defaults to NEWS_REDIS_URL")
    run_parser.add_argument("--now", default=None, help="Optional fixed current time as ISO datetime")
    run_parser.add_argument(
        "--include-disabled",
        action="store_true",
        help="Evaluate disabled schedules too",
    )
    run_parser.add_argument("--max-ticks", type=int, default=None, help="Stop after this many ticks")
    run_parser.add_argument(
        "--max-idle-ticks",
        type=int,
        default=None,
        help="Stop after this many ticks with no enqueued tasks",
    )
    run_parser.add_argument(
        "--tick-interval-seconds",
        type=float,
        default=60.0,
        help="Sleep interval between scheduler ticks",
    )
    run_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    run_parser.set_defaults(handler=run_schedules_from_cli)

    trigger_parser = schedules_subparsers.add_parser(
        "trigger",
        help="Manually trigger a schedule",
    )
    trigger_parser.add_argument("schedule_id", help="Schedule id")
    _add_store_path(trigger_parser)
    trigger_parser.add_argument("--redis-url", default=None, help="Redis URL; defaults to NEWS_REDIS_URL")
    trigger_parser.add_argument("--now", default=None, help="Optional current time as ISO datetime")
    trigger_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    trigger_parser.set_defaults(handler=trigger_schedule_from_cli)


def list_schedules_from_cli(args: argparse.Namespace) -> int:
    return list_schedules(args, schedule_service_factory=ScheduleApplicationService)


def add_daily_schedule_from_cli(args: argparse.Namespace) -> int:
    return add_daily_schedule(args, schedule_service_factory=ScheduleApplicationService)


def add_paper_reader_backfill_schedule_from_cli(args: argparse.Namespace) -> int:
    return add_paper_reader_backfill_schedule(args, schedule_service_factory=ScheduleApplicationService)


def tick_schedules_from_cli(args: argparse.Namespace) -> int:
    return tick_schedules(args, schedule_service_factory=ScheduleApplicationService)


def run_schedules_from_cli(args: argparse.Namespace) -> int:
    return run_schedules(args, schedule_service_factory=ScheduleApplicationService)


def trigger_schedule_from_cli(args: argparse.Namespace) -> int:
    return trigger_schedule(args, schedule_service_factory=ScheduleApplicationService)


def list_schedules(
    args: argparse.Namespace,
    *,
    schedule_service_factory: ScheduleServiceFactory,
) -> int:
    result = schedule_service_factory(store_path=args.store_path).list_schedules(
        enabled_only=args.enabled_only
    )
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"schedule_count={payload['schedule_count']}")
        for item in payload["schedules"]:
            spec = item["spec"]
            print(
                f"- {spec['schedule_id']} trigger={spec['trigger_type']} "
                f"enabled={str(spec['enabled']).lower()}"
            )
            print(f"  task_type={spec['task_type']} queue_name={spec['queue_name']}")
    return 0


def add_daily_schedule(
    args: argparse.Namespace,
    *,
    schedule_service_factory: ScheduleServiceFactory,
) -> int:
    if args.trigger_type == "interval" and args.interval_seconds <= 0:
        raise SystemExit("--interval-seconds must be greater than zero")
    run_at = parse_cli_datetime(args.run_at)
    result = schedule_service_factory(store_path=args.store_path).upsert_daily_schedule(
        schedule_id=args.schedule_id,
        name=args.name,
        trigger_type=args.trigger_type,
        interval_seconds=args.interval_seconds if args.trigger_type == "interval" else None,
        run_at=run_at if args.trigger_type == "interval" else None,
        profile=args.profile,
        topic=args.topic,
        source_limit=args.source_limit,
        queue_name=args.queue_name,
    )
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        spec_payload = payload["schedule"]["spec"]
        print(f"schedule_id={spec_payload['schedule_id']}")
        print(f"trigger_type={spec_payload['trigger_type']}")
        print(f"task_type={spec_payload['task_type']}")
        print(f"queue_name={spec_payload['queue_name']}")
    return 0


def add_paper_reader_backfill_schedule(
    args: argparse.Namespace,
    *,
    schedule_service_factory: ScheduleServiceFactory,
) -> int:
    if args.trigger_type == "interval" and args.interval_seconds <= 0:
        raise SystemExit("--interval-seconds must be greater than zero")
    if args.limit is not None and args.limit <= 0:
        raise SystemExit("--limit must be greater than zero")
    run_at = parse_cli_datetime(args.run_at)
    result = schedule_service_factory(store_path=args.store_path).upsert_paper_visual_compile_backfill_schedule(
        schedule_id=args.schedule_id,
        name=args.name,
        trigger_type=args.trigger_type,
        interval_seconds=args.interval_seconds if args.trigger_type == "interval" else None,
        run_at=run_at if args.trigger_type == "interval" else None,
        limit=args.limit,
        force=args.force,
        queue_name=args.queue_name,
    )
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        spec_payload = payload["schedule"]["spec"]
        print(f"schedule_id={spec_payload['schedule_id']}")
        print(f"trigger_type={spec_payload['trigger_type']}")
        print(f"task_type={spec_payload['task_type']}")
        print(f"queue_name={spec_payload['queue_name']}")
    return 0


def tick_schedules(
    args: argparse.Namespace,
    *,
    schedule_service_factory: ScheduleServiceFactory,
) -> int:
    result = schedule_service_factory(
        store_path=args.store_path,
        redis_url=args.redis_url,
    ).tick(
        now=parse_cli_datetime(args.now),
        enabled_only=not args.include_disabled,
    )
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"evaluated_count={payload['evaluated_count']}")
        print(f"enqueued_count={payload['enqueued_count']}")
        for item in payload["enqueued"]:
            task = item["task"]
            print(f"- {item['schedule_id']} task_id={task['task_id']} message_id={item['message_id']}")
    return 0


def run_schedules(
    args: argparse.Namespace,
    *,
    schedule_service_factory: ScheduleServiceFactory,
) -> int:
    try:
        result = schedule_service_factory(
            store_path=args.store_path,
            redis_url=args.redis_url,
        ).run_loop(
            now=parse_cli_datetime(args.now),
            enabled_only=not args.include_disabled,
            max_ticks=args.max_ticks,
            max_idle_ticks=args.max_idle_ticks,
            tick_interval_seconds=args.tick_interval_seconds,
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    except KeyboardInterrupt:
        print("scheduler interrupted")
        return 130
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"stop_reason={payload['stop_reason']}")
        print(f"tick_count={payload['tick_count']}")
        print(f"enqueued_count={payload['enqueued_count']}")
        print(f"idle_tick_count={payload['idle_tick_count']}")
    return 0


def trigger_schedule(
    args: argparse.Namespace,
    *,
    schedule_service_factory: ScheduleServiceFactory,
) -> int:
    result = schedule_service_factory(
        store_path=args.store_path,
        redis_url=args.redis_url,
    ).trigger_manual(
        args.schedule_id,
        now=parse_cli_datetime(args.now),
    )
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        task = payload["enqueued"]["task"]
        print(f"schedule_id={payload['schedule_id']}")
        print(f"task_id={task['task_id']}")
        print(f"message_id={payload['enqueued']['message_id']}")
    return 0


def parse_cli_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError as exc:
        raise SystemExit(f"invalid ISO datetime: {value}") from exc


def _add_store_path(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--store-path",
        default=DEFAULT_SCHEDULE_STORE_PATH,
        help="Local JSON schedule store path",
    )


add_schedules_commands = register


__all__ = [
    "CommandHandler",
    "ScheduleServiceFactory",
    "add_daily_schedule",
    "add_daily_schedule_from_cli",
    "add_paper_reader_backfill_schedule",
    "add_paper_reader_backfill_schedule_from_cli",
    "add_schedules_commands",
    "call_handler",
    "list_schedules",
    "list_schedules_from_cli",
    "parse_cli_datetime",
    "register",
    "run_schedules",
    "run_schedules_from_cli",
    "tick_schedules",
    "tick_schedules_from_cli",
    "trigger_schedule",
    "trigger_schedule_from_cli",
]
