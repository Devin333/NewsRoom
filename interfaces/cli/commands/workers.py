from __future__ import annotations

import argparse
import json

from interfaces.cli.commands.dispatch import CommandHandler, call_handler
from interfaces.services.worker_service import (
    DEFAULT_WORKER_STATUS,
    DEFAULT_DEAD_LETTER_QUEUE,
    DEFAULT_MEMORY_QUEUE,
    DEFAULT_SOURCE_QUEUE,
    WorkerApplicationService,
    WORKER_STATUS_CHOICES,
)


def register(subparsers: argparse._SubParsersAction) -> None:
    _register_worker_tree(subparsers, "worker")
    _register_worker_tree(subparsers, "workers")


def _register_worker_tree(subparsers: argparse._SubParsersAction, command_name: str) -> None:
    worker_parser = subparsers.add_parser(command_name, help="Submit and process background tasks")
    worker_subparsers = worker_parser.add_subparsers(dest="worker_command", required=True)

    enqueue_memory_parser = worker_subparsers.add_parser(
        "enqueue-memory-reindex",
        help="Enqueue a memory reindex task",
    )
    enqueue_memory_parser.add_argument("--run-id", required=True, help="Run id to reindex")
    enqueue_memory_parser.add_argument("--topic", default=None, help="Optional topic override")
    enqueue_memory_parser.add_argument("--queue-name", default=DEFAULT_MEMORY_QUEUE, help="Redis stream queue name")
    enqueue_memory_parser.add_argument("--redis-url", default=None, help="Redis URL; defaults to NEWS_REDIS_URL")
    enqueue_memory_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    enqueue_memory_parser.set_defaults(handler=enqueue_memory_reindex)

    enqueue_source_health_parser = worker_subparsers.add_parser(
        "enqueue-source-health",
        help="Enqueue a source health check task",
    )
    enqueue_source_health_parser.add_argument("--source-id", default=None, help="Optional source id to check")
    enqueue_source_health_parser.add_argument("--include-disabled", action="store_true", help="Include disabled sources")
    enqueue_source_health_parser.add_argument("--limit", type=int, default=None, help="Maximum sources to check")
    enqueue_source_health_parser.add_argument("--force", action="store_true", help="Probe even during cooldown")
    enqueue_source_health_parser.add_argument("--queue-name", default=DEFAULT_SOURCE_QUEUE, help="Redis stream queue name")
    enqueue_source_health_parser.add_argument("--redis-url", default=None, help="Redis URL; defaults to NEWS_REDIS_URL")
    enqueue_source_health_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    enqueue_source_health_parser.set_defaults(handler=enqueue_source_health)

    run_once_parser = worker_subparsers.add_parser(
        "run-once",
        help="Lease and process at most one queued task",
    )
    run_once_parser.add_argument("--worker-id", default="news-worker-1", help="Worker consumer id")
    _add_queue_names(run_once_parser)
    run_once_parser.add_argument("--block-ms", type=int, default=1000, help="Redis read block time in milliseconds")
    run_once_parser.add_argument(
        "--reclaim-stale-ms",
        type=int,
        default=None,
        help="Claim pending tasks idle for at least this many milliseconds when no new task is available",
    )
    _add_artifact_root(run_once_parser)
    run_once_parser.add_argument("--redis-url", default=None, help="Redis URL; defaults to NEWS_REDIS_URL")
    run_once_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    run_once_parser.set_defaults(handler=run_once)

    run_worker_parser = worker_subparsers.add_parser(
        "run",
        help="Continuously process queued worker tasks",
    )
    run_worker_parser.add_argument("--worker-id", default="news-worker-1", help="Worker consumer id")
    _add_queue_names(run_worker_parser)
    run_worker_parser.add_argument("--block-ms", type=int, default=1000, help="Redis read block time in milliseconds")
    run_worker_parser.add_argument(
        "--reclaim-stale-ms",
        type=int,
        default=None,
        help="Claim pending tasks idle for at least this many milliseconds when no new task is available",
    )
    run_worker_parser.add_argument("--max-tasks", type=int, default=None, help="Stop after processing this many tasks")
    run_worker_parser.add_argument(
        "--max-idle-polls",
        type=int,
        default=None,
        help="Stop after this many idle polls",
    )
    run_worker_parser.add_argument(
        "--idle-sleep-seconds",
        type=float,
        default=1.0,
        help="Sleep interval after idle polls",
    )
    _add_artifact_root(run_worker_parser)
    run_worker_parser.add_argument("--redis-url", default=None, help="Redis URL; defaults to NEWS_REDIS_URL")
    run_worker_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    run_worker_parser.set_defaults(handler=run_loop)

    heartbeat_parser = worker_subparsers.add_parser(
        "heartbeat",
        help="Record a worker heartbeat",
    )
    heartbeat_parser.add_argument("--worker-id", required=True, help="Worker id")
    _add_queue_names(heartbeat_parser)
    heartbeat_parser.add_argument(
        "--status",
        choices=WORKER_STATUS_CHOICES,
        default=DEFAULT_WORKER_STATUS,
        help="Worker lifecycle status",
    )
    heartbeat_parser.add_argument("--current-task-id", default=None, help="Current task id, if any")
    heartbeat_parser.add_argument("--redis-url", default=None, help="Redis URL; defaults to NEWS_REDIS_URL")
    heartbeat_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    heartbeat_parser.set_defaults(handler=heartbeat)

    worker_status_parser = worker_subparsers.add_parser(
        "status",
        help="Read worker heartbeat status",
    )
    worker_status_parser.add_argument("--worker-id", default=None, help="Filter to one worker id")
    worker_status_parser.add_argument(
        "--stale-after-seconds",
        type=int,
        default=60,
        help="Mark workers unhealthy after this many seconds without heartbeat",
    )
    worker_status_parser.add_argument("--redis-url", default=None, help="Redis URL; defaults to NEWS_REDIS_URL")
    worker_status_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    worker_status_parser.set_defaults(handler=status)

    worker_queues_parser = worker_subparsers.add_parser(
        "queues",
        help="Read Redis worker queue status",
    )
    _add_queue_names(worker_queues_parser)
    worker_queues_parser.add_argument("--redis-url", default=None, help="Redis URL; defaults to NEWS_REDIS_URL")
    worker_queues_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    worker_queues_parser.set_defaults(handler=queues)


def enqueue_memory_reindex(args: argparse.Namespace) -> int:
    service = _worker_service(redis_url=args.redis_url)
    result = service.enqueue_memory_reindex(
        run_id=args.run_id,
        topic=args.topic,
        queue_name=args.queue_name,
    )
    payload = result.to_dict()

    if args.json:
        _print_json(payload)
    else:
        print(f"task_id={payload['task_id']}")
        print(f"task_type={payload['task_type']}")
        print(f"queue_name={payload['queue_name']}")
        print(f"message_id={payload['message_id']}")
        print(f"run_id={payload['run_id']}")
        if payload["topic"]:
            print(f"topic={payload['topic']}")
    return 0


def enqueue_source_health(args: argparse.Namespace) -> int:
    service = _worker_service(redis_url=args.redis_url)
    try:
        result = service.enqueue_source_health_check(
            source_id=args.source_id,
            include_disabled=args.include_disabled,
            limit=args.limit,
            force=args.force,
            queue_name=args.queue_name,
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()

    if args.json:
        _print_json(payload)
    else:
        print(f"task_id={payload['task_id']}")
        print(f"task_type={payload['task_type']}")
        print(f"queue_name={payload['queue_name']}")
        print(f"message_id={payload['message_id']}")
    return 0


def run_once(args: argparse.Namespace) -> int:
    service = _worker_service(artifact_root=args.artifact_root, redis_url=args.redis_url)
    try:
        result = service.run_once(
            worker_id=args.worker_id,
            queue_names=args.queue_names or [DEFAULT_MEMORY_QUEUE],
            block_ms=args.block_ms,
            reclaim_stale_ms=args.reclaim_stale_ms,
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()

    if args.json:
        _print_json(payload)
    else:
        print(f"processed={str(payload['processed']).lower()}")
        print(f"worker_id={payload['worker_id']}")
        if payload["processed"]:
            print(f"task_id={payload['task_id']}")
            print(f"task_type={payload['task_type']}")
            print(f"queue_name={payload['queue_name']}")
            print(f"message_id={payload['message_id']}")
            print(f"reclaimed={str(payload.get('reclaimed')).lower()}")
            print(f"success={str(payload['success']).lower()}")
            print(f"graph_identity={payload['graph_identity']}")
            if payload["error_message"]:
                print(f"error={payload['error_message']}")
    return 0 if result.success is not False else 1


def run_loop(args: argparse.Namespace) -> int:
    service = _worker_service(artifact_root=args.artifact_root, redis_url=args.redis_url)
    try:
        result = service.run_loop(
            worker_id=args.worker_id,
            queue_names=args.queue_names or [DEFAULT_MEMORY_QUEUE],
            block_ms=args.block_ms,
            reclaim_stale_ms=args.reclaim_stale_ms,
            max_tasks=args.max_tasks,
            max_idle_polls=args.max_idle_polls,
            idle_sleep_seconds=args.idle_sleep_seconds,
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    except KeyboardInterrupt:
        print("worker interrupted")
        return 130
    payload = result.to_dict()

    if args.json:
        _print_json(payload)
    else:
        print(f"worker_id={payload['worker_id']}")
        print(f"stop_reason={payload['stop_reason']}")
        print(f"iterations={payload['iterations']}")
        print(f"processed_count={payload['processed_count']}")
        print(f"succeeded_count={payload['succeeded_count']}")
        print(f"failed_count={payload['failed_count']}")
        print(f"idle_count={payload['idle_count']}")
    return 0 if payload["failed_count"] == 0 else 1


def heartbeat(args: argparse.Namespace) -> int:
    service = _worker_service(redis_url=args.redis_url)
    result = service.record_heartbeat(
        worker_id=args.worker_id,
        queue_names=args.queue_names or [DEFAULT_MEMORY_QUEUE],
        status=args.status,
        current_task_id=args.current_task_id,
    )
    payload = result.to_dict()

    if args.json:
        _print_json(payload)
    else:
        worker = payload["worker"]
        print(f"worker_id={worker['worker_id']}")
        print(f"status={worker['status']}")
        print(f"stale={str(worker['stale']).lower()}")
        print(f"last_heartbeat_at={worker['last_heartbeat_at']}")
    return 0


def status(args: argparse.Namespace) -> int:
    try:
        result = _worker_service(redis_url=args.redis_url).list_worker_status(
            worker_id=args.worker_id,
            stale_after_seconds=args.stale_after_seconds,
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()

    if args.json:
        _print_json(payload)
    else:
        print(f"worker_count={payload['worker_count']}")
        print(f"unhealthy_count={payload['unhealthy_count']}")
        for worker in payload["workers"]:
            print(
                f"- {worker['worker_id']} status={worker['status']} "
                f"stale={str(worker['stale']).lower()} heartbeat={worker['last_heartbeat_at']}"
            )
    return 0


def queues(args: argparse.Namespace) -> int:
    result = _worker_service(redis_url=args.redis_url).queue_status(
        queue_names=args.queue_names
        or [DEFAULT_MEMORY_QUEUE, DEFAULT_SOURCE_QUEUE, DEFAULT_DEAD_LETTER_QUEUE]
    )
    payload = result.to_dict()

    if args.json:
        _print_json(payload)
    else:
        print(f"queue_count={payload['queue_count']}")
        print(f"total_stream_length={payload['total_stream_length']}")
        print(f"total_pending_count={payload['total_pending_count']}")
        for queue in payload["queues"]:
            print(
                f"- {queue['queue_name']} length={queue['stream_length']} "
                f"pending={queue['pending_count']} group_exists={str(queue['group_exists']).lower()}"
            )
    return 0


def _worker_service(*args, **kwargs):
    return WorkerApplicationService(*args, **kwargs)


def _add_queue_names(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--queue-name",
        dest="queue_names",
        action="append",
        default=None,
        help="Queue stream to read; can be passed multiple times",
    )


def _add_artifact_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--artifact-root",
        default=".newsroom/runs",
        help="Directory where run artifacts are written",
    )


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


add_workers_commands = register


__all__ = [
    "CommandHandler",
    "add_workers_commands",
    "call_handler",
    "enqueue_memory_reindex",
    "enqueue_source_health",
    "heartbeat",
    "queues",
    "register",
    "run_loop",
    "run_once",
    "status",
]
