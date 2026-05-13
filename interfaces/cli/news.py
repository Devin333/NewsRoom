from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

from core.framework.specs import WorkflowStatus
from core.framework.tools import ToolPolicy, build_builtin_tool_registry, build_tool_catalog
from core.framework.workers import WorkerStatus
from core.framework.workers.approval import ApprovalAlreadyDecidedError, ApprovalNotFoundError
from core.framework.workers.schedule_store import ScheduleRecord
from core.framework.workers.scheduler import ScheduleSpec
from interfaces.services.approval_service import (
    ApprovalApplicationService,
    DEFAULT_APPROVAL_STORE_PATH,
)
from interfaces.services.artifact_service import ArtifactInspectionService
from interfaces.services.diagnose_service import DiagnosticApplicationService
from interfaces.services.entity_service import (
    DEFAULT_ENTITY_STORE_PATH,
    EntityTrackingApplicationService,
)
from interfaces.services.memory_service import DEFAULT_MEMORY_COLLECTION, MemoryApplicationService
from interfaces.services.mcp_service import MCPApplicationService
from interfaces.services.report_service import ReportApplicationService
from interfaces.services.run_inspection_service import RunInspectionService
from interfaces.services.run_service import RunApplicationService
from interfaces.services.schedule_service import (
    DEFAULT_SCHEDULE_STORE_PATH,
    ScheduleApplicationService,
)
from interfaces.services.source_service import SourceApplicationService
from interfaces.services.storage_service import StorageApplicationService
from interfaces.services.subscription_service import (
    DEFAULT_SUBSCRIPTION_STORE_PATH,
    SubscriptionApplicationService,
)
from interfaces.services.worker_service import (
    DEFAULT_DAILY_QUEUE,
    DEFAULT_DEAD_LETTER_QUEUE,
    DEFAULT_MEMORY_QUEUE,
    DEFAULT_SOURCE_QUEUE,
    WorkerApplicationService,
)
from storage.lifecycle import RetentionPolicy


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="news", description="NewsRoom command line interface")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run product workflows")
    run_subparsers = run_parser.add_subparsers(dest="run_command", required=True)
    daily_parser = run_subparsers.add_parser("daily", help="Run daily intelligence workflow")
    daily_parser.add_argument(
        "--profile",
        choices=["live", "live-offline"],
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
    daily_parser.set_defaults(handler=_run_daily)

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
    weekly_parser.set_defaults(handler=_run_weekly)

    latest_parser = subparsers.add_parser("latest", help="Show latest local report")
    latest_parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format",
    )
    latest_parser.add_argument(
        "--artifact-root",
        default=".newsroom/runs",
        help="Directory where run artifacts are stored",
    )
    latest_parser.set_defaults(handler=_latest_report)

    reports_parser = subparsers.add_parser("reports", help="Inspect persisted reports")
    reports_subparsers = reports_parser.add_subparsers(dest="reports_command", required=True)

    reports_list_parser = reports_subparsers.add_parser("list", help="List persisted reports")
    reports_list_parser.add_argument("--limit", type=int, default=20, help="Maximum reports")
    reports_list_parser.add_argument("--workflow-id", default=None, help="Optional workflow id filter")
    reports_list_parser.add_argument(
        "--artifact-root",
        default=".newsroom/runs",
        help="Directory where run artifacts are stored",
    )
    reports_list_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    reports_list_parser.set_defaults(handler=_reports_list)

    reports_show_parser = reports_subparsers.add_parser("show", help="Show one persisted report")
    reports_show_parser.add_argument("report_id", help="Report id")
    reports_show_parser.add_argument(
        "--artifact-root",
        default=".newsroom/runs",
        help="Directory where run artifacts are stored",
    )
    reports_show_parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format",
    )
    reports_show_parser.set_defaults(handler=_reports_show)

    reports_search_parser = reports_subparsers.add_parser("search", help="Search persisted reports")
    reports_search_parser.add_argument("query", help="Search query")
    reports_search_parser.add_argument("--limit", type=int, default=20, help="Maximum reports")
    reports_search_parser.add_argument(
        "--artifact-root",
        default=".newsroom/runs",
        help="Directory where run artifacts are stored",
    )
    reports_search_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    reports_search_parser.set_defaults(handler=_reports_search)

    subscriptions_parser = subparsers.add_parser("subscriptions", help="Manage topic subscriptions")
    subscriptions_subparsers = subscriptions_parser.add_subparsers(
        dest="subscriptions_command",
        required=True,
    )
    subscriptions_create_parser = subscriptions_subparsers.add_parser(
        "create",
        help="Create or update a topic subscription",
    )
    subscriptions_create_parser.add_argument("--topic", required=True, help="Topic to track")
    subscriptions_create_parser.add_argument("--subscription-id", default=None, help="Optional subscription id")
    subscriptions_create_parser.add_argument("--cadence", choices=["daily", "weekly"], default="weekly")
    subscriptions_create_parser.add_argument(
        "--profile",
        choices=["live", "live-offline"],
        default="live-offline",
    )
    subscriptions_create_parser.add_argument("--source-limit", type=int, default=5)
    subscriptions_create_parser.add_argument("--disabled", action="store_true")
    subscriptions_create_parser.add_argument(
        "--metadata",
        action="append",
        default=None,
        help="Metadata key=value; repeat for multiple values",
    )
    subscriptions_create_parser.add_argument(
        "--store-path",
        default=DEFAULT_SUBSCRIPTION_STORE_PATH,
        help="Local JSON subscription store path",
    )
    subscriptions_create_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    subscriptions_create_parser.set_defaults(handler=_subscriptions_create)

    subscriptions_list_parser = subscriptions_subparsers.add_parser("list", help="List topic subscriptions")
    subscriptions_list_parser.add_argument("--enabled-only", action="store_true")
    subscriptions_list_parser.add_argument("--cadence", choices=["daily", "weekly"], default=None)
    subscriptions_list_parser.add_argument(
        "--store-path",
        default=DEFAULT_SUBSCRIPTION_STORE_PATH,
        help="Local JSON subscription store path",
    )
    subscriptions_list_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    subscriptions_list_parser.set_defaults(handler=_subscriptions_list)

    subscriptions_enable_parser = subscriptions_subparsers.add_parser("enable", help="Enable a topic subscription")
    subscriptions_enable_parser.add_argument("subscription_id")
    subscriptions_enable_parser.add_argument("--store-path", default=DEFAULT_SUBSCRIPTION_STORE_PATH)
    subscriptions_enable_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    subscriptions_enable_parser.set_defaults(handler=_subscriptions_enable)

    subscriptions_disable_parser = subscriptions_subparsers.add_parser("disable", help="Disable a topic subscription")
    subscriptions_disable_parser.add_argument("subscription_id")
    subscriptions_disable_parser.add_argument("--store-path", default=DEFAULT_SUBSCRIPTION_STORE_PATH)
    subscriptions_disable_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    subscriptions_disable_parser.set_defaults(handler=_subscriptions_disable)

    subscriptions_delete_parser = subscriptions_subparsers.add_parser("delete", help="Delete a topic subscription")
    subscriptions_delete_parser.add_argument("subscription_id")
    subscriptions_delete_parser.add_argument("--store-path", default=DEFAULT_SUBSCRIPTION_STORE_PATH)
    subscriptions_delete_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    subscriptions_delete_parser.set_defaults(handler=_subscriptions_delete)

    entities_parser = subparsers.add_parser("entities", help="Manage tracked entities")
    entities_subparsers = entities_parser.add_subparsers(dest="entities_command", required=True)

    entities_create_parser = entities_subparsers.add_parser(
        "create",
        help="Create or update a tracked entity",
    )
    entities_create_parser.add_argument("--name", required=True, help="Entity display name")
    entities_create_parser.add_argument(
        "--kind",
        choices=["company", "project", "person", "organization"],
        default="company",
    )
    entities_create_parser.add_argument("--entity-id", default=None, help="Optional entity id")
    entities_create_parser.add_argument("--alias", action="append", default=None, help="Alias; repeatable")
    entities_create_parser.add_argument("--disabled", action="store_true")
    entities_create_parser.add_argument(
        "--metadata",
        action="append",
        default=None,
        help="Metadata key=value; repeat for multiple values",
    )
    entities_create_parser.add_argument("--store-path", default=DEFAULT_ENTITY_STORE_PATH)
    entities_create_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    entities_create_parser.set_defaults(handler=_entities_create)

    entities_list_parser = entities_subparsers.add_parser("list", help="List tracked entities")
    entities_list_parser.add_argument("--enabled-only", action="store_true")
    entities_list_parser.add_argument(
        "--kind",
        choices=["company", "project", "person", "organization"],
        default=None,
    )
    entities_list_parser.add_argument("--store-path", default=DEFAULT_ENTITY_STORE_PATH)
    entities_list_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    entities_list_parser.set_defaults(handler=_entities_list)

    entities_enable_parser = entities_subparsers.add_parser("enable", help="Enable a tracked entity")
    entities_enable_parser.add_argument("entity_id")
    entities_enable_parser.add_argument("--store-path", default=DEFAULT_ENTITY_STORE_PATH)
    entities_enable_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    entities_enable_parser.set_defaults(handler=_entities_enable)

    entities_disable_parser = entities_subparsers.add_parser("disable", help="Disable a tracked entity")
    entities_disable_parser.add_argument("entity_id")
    entities_disable_parser.add_argument("--store-path", default=DEFAULT_ENTITY_STORE_PATH)
    entities_disable_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    entities_disable_parser.set_defaults(handler=_entities_disable)

    entities_delete_parser = entities_subparsers.add_parser("delete", help="Delete a tracked entity")
    entities_delete_parser.add_argument("entity_id")
    entities_delete_parser.add_argument("--store-path", default=DEFAULT_ENTITY_STORE_PATH)
    entities_delete_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    entities_delete_parser.set_defaults(handler=_entities_delete)

    entities_match_parser = entities_subparsers.add_parser(
        "match-reports",
        help="Match a tracked entity against persisted reports",
    )
    entities_match_parser.add_argument("entity_id")
    entities_match_parser.add_argument("--store-path", default=DEFAULT_ENTITY_STORE_PATH)
    entities_match_parser.add_argument("--artifact-root", default=".newsroom/runs")
    entities_match_parser.add_argument("--limit", type=int, default=20)
    entities_match_parser.add_argument("--workflow-id", default=None)
    entities_match_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    entities_match_parser.set_defaults(handler=_entities_match_reports)

    api_parser = subparsers.add_parser("api", help="Run HTTP API server")
    api_subparsers = api_parser.add_subparsers(dest="api_command", required=True)
    api_serve_parser = api_subparsers.add_parser("serve", help="Serve the HTTP API")
    api_serve_parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    api_serve_parser.add_argument("--port", type=int, default=8000, help="Bind port")
    api_serve_parser.add_argument("--reload", action="store_true", help="Enable uvicorn reload")
    api_serve_parser.add_argument(
        "--log-level",
        choices=["critical", "error", "warning", "info", "debug", "trace"],
        default="info",
        help="Uvicorn log level",
    )
    api_serve_parser.set_defaults(handler=_api_serve)

    api_openapi_parser = api_subparsers.add_parser("openapi", help="Export HTTP API OpenAPI schema")
    api_openapi_parser.add_argument("--json", action="store_true", help="Print full OpenAPI JSON")
    api_openapi_parser.add_argument("--output", default=None, help="Write OpenAPI JSON to this path")
    api_openapi_parser.set_defaults(handler=_api_openapi)

    worker_parser = subparsers.add_parser("worker", help="Submit and process background tasks")
    worker_subparsers = worker_parser.add_subparsers(dest="worker_command", required=True)

    enqueue_daily_parser = worker_subparsers.add_parser(
        "enqueue-daily",
        help="Enqueue a daily intelligence task",
    )
    enqueue_daily_parser.add_argument(
        "--profile",
        choices=["live", "live-offline"],
        default="live-offline",
        help="Execution profile",
    )
    enqueue_daily_parser.add_argument("--topic", default="AI", help="Topic for the daily report")
    enqueue_daily_parser.add_argument("--source-limit", type=int, default=3, help="Maximum source items")
    enqueue_daily_parser.add_argument("--run-id", default=None, help="Optional deterministic run id")
    enqueue_daily_parser.add_argument("--queue-name", default=DEFAULT_DAILY_QUEUE, help="Redis stream queue name")
    enqueue_daily_parser.add_argument("--redis-url", default=None, help="Redis URL; defaults to NEWS_REDIS_URL")
    enqueue_daily_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    enqueue_daily_parser.set_defaults(handler=_worker_enqueue_daily)

    enqueue_memory_parser = worker_subparsers.add_parser(
        "enqueue-memory-reindex",
        help="Enqueue a memory reindex task",
    )
    enqueue_memory_parser.add_argument("--run-id", required=True, help="Run id to reindex")
    enqueue_memory_parser.add_argument("--topic", default=None, help="Optional topic override")
    enqueue_memory_parser.add_argument("--queue-name", default=DEFAULT_MEMORY_QUEUE, help="Redis stream queue name")
    enqueue_memory_parser.add_argument("--redis-url", default=None, help="Redis URL; defaults to NEWS_REDIS_URL")
    enqueue_memory_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    enqueue_memory_parser.set_defaults(handler=_worker_enqueue_memory_reindex)

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
    enqueue_source_health_parser.set_defaults(handler=_worker_enqueue_source_health)

    run_once_parser = worker_subparsers.add_parser(
        "run-once",
        help="Lease and process at most one queued task",
    )
    run_once_parser.add_argument("--worker-id", default="news-worker-1", help="Worker consumer id")
    run_once_parser.add_argument(
        "--queue-name",
        dest="queue_names",
        action="append",
        default=None,
        help="Queue stream to read; can be passed multiple times",
    )
    run_once_parser.add_argument("--block-ms", type=int, default=1000, help="Redis read block time in milliseconds")
    run_once_parser.add_argument(
        "--reclaim-stale-ms",
        type=int,
        default=None,
        help="Claim pending tasks idle for at least this many milliseconds when no new task is available",
    )
    run_once_parser.add_argument(
        "--artifact-root",
        default=".newsroom/runs",
        help="Directory where run artifacts are written",
    )
    run_once_parser.add_argument("--redis-url", default=None, help="Redis URL; defaults to NEWS_REDIS_URL")
    run_once_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    run_once_parser.set_defaults(handler=_worker_run_once)

    run_worker_parser = worker_subparsers.add_parser(
        "run",
        help="Continuously process queued worker tasks",
    )
    run_worker_parser.add_argument("--worker-id", default="news-worker-1", help="Worker consumer id")
    run_worker_parser.add_argument(
        "--queue-name",
        dest="queue_names",
        action="append",
        default=None,
        help="Queue stream to read; can be passed multiple times",
    )
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
    run_worker_parser.add_argument(
        "--artifact-root",
        default=".newsroom/runs",
        help="Directory where run artifacts are written",
    )
    run_worker_parser.add_argument("--redis-url", default=None, help="Redis URL; defaults to NEWS_REDIS_URL")
    run_worker_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    run_worker_parser.set_defaults(handler=_worker_run)

    heartbeat_parser = worker_subparsers.add_parser(
        "heartbeat",
        help="Record a worker heartbeat",
    )
    heartbeat_parser.add_argument("--worker-id", required=True, help="Worker id")
    heartbeat_parser.add_argument(
        "--queue-name",
        dest="queue_names",
        action="append",
        default=None,
        help="Queue stream handled by the worker; can be passed multiple times",
    )
    heartbeat_parser.add_argument(
        "--status",
        choices=[status.value for status in WorkerStatus],
        default=WorkerStatus.RUNNING.value,
        help="Worker lifecycle status",
    )
    heartbeat_parser.add_argument("--current-task-id", default=None, help="Current task id, if any")
    heartbeat_parser.add_argument("--redis-url", default=None, help="Redis URL; defaults to NEWS_REDIS_URL")
    heartbeat_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    heartbeat_parser.set_defaults(handler=_worker_heartbeat)

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
    worker_status_parser.set_defaults(handler=_worker_status)

    worker_queues_parser = worker_subparsers.add_parser(
        "queues",
        help="Read Redis worker queue status",
    )
    worker_queues_parser.add_argument(
        "--queue-name",
        dest="queue_names",
        action="append",
        default=None,
        help="Queue stream to inspect; can be passed multiple times",
    )
    worker_queues_parser.add_argument("--redis-url", default=None, help="Redis URL; defaults to NEWS_REDIS_URL")
    worker_queues_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    worker_queues_parser.set_defaults(handler=_worker_queues)

    schedules_parser = subparsers.add_parser("schedules", help="Manage background schedules")
    schedules_subparsers = schedules_parser.add_subparsers(dest="schedules_command", required=True)

    schedules_list_parser = schedules_subparsers.add_parser("list", help="List schedules")
    schedules_list_parser.add_argument("--enabled-only", action="store_true", help="Only include enabled schedules")
    schedules_list_parser.add_argument(
        "--store-path",
        default=DEFAULT_SCHEDULE_STORE_PATH,
        help="Local JSON schedule store path",
    )
    schedules_list_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    schedules_list_parser.set_defaults(handler=_schedules_list)

    schedules_add_daily_parser = schedules_subparsers.add_parser(
        "add-daily",
        help="Create or update a daily intelligence schedule",
    )
    schedules_add_daily_parser.add_argument("--schedule-id", default="daily-intelligence", help="Schedule id")
    schedules_add_daily_parser.add_argument("--name", default="Daily intelligence", help="Schedule name")
    schedules_add_daily_parser.add_argument(
        "--trigger-type",
        choices=["interval", "manual"],
        default="interval",
        help="Schedule trigger type",
    )
    schedules_add_daily_parser.add_argument(
        "--interval-seconds",
        type=int,
        default=86400,
        help="Interval in seconds for interval schedules",
    )
    schedules_add_daily_parser.add_argument("--run-at", default=None, help="Optional first due time as ISO datetime")
    schedules_add_daily_parser.add_argument(
        "--profile",
        choices=["live", "live-offline"],
        default="live-offline",
        help="Execution profile",
    )
    schedules_add_daily_parser.add_argument("--topic", default="AI", help="Topic for the daily report")
    schedules_add_daily_parser.add_argument("--source-limit", type=int, default=3, help="Maximum source items")
    schedules_add_daily_parser.add_argument("--queue-name", default=DEFAULT_DAILY_QUEUE, help="Queue name")
    schedules_add_daily_parser.add_argument(
        "--store-path",
        default=DEFAULT_SCHEDULE_STORE_PATH,
        help="Local JSON schedule store path",
    )
    schedules_add_daily_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    schedules_add_daily_parser.set_defaults(handler=_schedules_add_daily)

    schedules_tick_parser = schedules_subparsers.add_parser("tick", help="Evaluate schedules and enqueue due tasks")
    schedules_tick_parser.add_argument(
        "--store-path",
        default=DEFAULT_SCHEDULE_STORE_PATH,
        help="Local JSON schedule store path",
    )
    schedules_tick_parser.add_argument("--redis-url", default=None, help="Redis URL; defaults to NEWS_REDIS_URL")
    schedules_tick_parser.add_argument("--now", default=None, help="Optional current time as ISO datetime")
    schedules_tick_parser.add_argument(
        "--include-disabled",
        action="store_true",
        help="Evaluate disabled schedules too",
    )
    schedules_tick_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    schedules_tick_parser.set_defaults(handler=_schedules_tick)

    schedules_run_parser = schedules_subparsers.add_parser(
        "run",
        help="Continuously evaluate schedules and enqueue due tasks",
    )
    schedules_run_parser.add_argument(
        "--store-path",
        default=DEFAULT_SCHEDULE_STORE_PATH,
        help="Local JSON schedule store path",
    )
    schedules_run_parser.add_argument("--redis-url", default=None, help="Redis URL; defaults to NEWS_REDIS_URL")
    schedules_run_parser.add_argument("--now", default=None, help="Optional fixed current time as ISO datetime")
    schedules_run_parser.add_argument(
        "--include-disabled",
        action="store_true",
        help="Evaluate disabled schedules too",
    )
    schedules_run_parser.add_argument("--max-ticks", type=int, default=None, help="Stop after this many ticks")
    schedules_run_parser.add_argument(
        "--max-idle-ticks",
        type=int,
        default=None,
        help="Stop after this many ticks with no enqueued tasks",
    )
    schedules_run_parser.add_argument(
        "--tick-interval-seconds",
        type=float,
        default=60.0,
        help="Sleep interval between scheduler ticks",
    )
    schedules_run_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    schedules_run_parser.set_defaults(handler=_schedules_run)

    schedules_trigger_parser = schedules_subparsers.add_parser(
        "trigger",
        help="Manually trigger a schedule",
    )
    schedules_trigger_parser.add_argument("schedule_id", help="Schedule id")
    schedules_trigger_parser.add_argument(
        "--store-path",
        default=DEFAULT_SCHEDULE_STORE_PATH,
        help="Local JSON schedule store path",
    )
    schedules_trigger_parser.add_argument("--redis-url", default=None, help="Redis URL; defaults to NEWS_REDIS_URL")
    schedules_trigger_parser.add_argument("--now", default=None, help="Optional current time as ISO datetime")
    schedules_trigger_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    schedules_trigger_parser.set_defaults(handler=_schedules_trigger)

    approvals_parser = subparsers.add_parser("approvals", help="Manage human approvals")
    approvals_subparsers = approvals_parser.add_subparsers(dest="approvals_command", required=True)

    approvals_list_parser = approvals_subparsers.add_parser("list", help="List approval requests")
    approvals_list_parser.add_argument(
        "--status",
        choices=["pending", "approved", "rejected", "modified", "expired", "cancelled"],
        default=None,
        help="Filter by approval status",
    )
    approvals_list_parser.add_argument(
        "--store-path",
        default=DEFAULT_APPROVAL_STORE_PATH,
        help="Local JSON approval store path",
    )
    approvals_list_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    approvals_list_parser.set_defaults(handler=_approvals_list)

    approvals_submit_parser = approvals_subparsers.add_parser("submit", help="Submit an approval request")
    approvals_submit_parser.add_argument("--requested-action", required=True, help="Action requiring approval")
    approvals_submit_parser.add_argument("--risk-level", default="medium", help="Risk level")
    approvals_submit_parser.add_argument("--reason", default=None, help="Reason for approval")
    approvals_submit_parser.add_argument("--payload-json", default="{}", help="Approval payload JSON object")
    approvals_submit_parser.add_argument("--task-id", default=None, help="Related task id")
    approvals_submit_parser.add_argument("--run-id", default=None, help="Related workflow run id")
    approvals_submit_parser.add_argument("--requested-by", default=None, help="Requester id")
    approvals_submit_parser.add_argument("--expires-at", default=None, help="Optional expiry as ISO datetime")
    approvals_submit_parser.add_argument("--metadata-json", default="{}", help="Approval metadata JSON object")
    approvals_submit_parser.add_argument(
        "--store-path",
        default=DEFAULT_APPROVAL_STORE_PATH,
        help="Local JSON approval store path",
    )
    approvals_submit_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    approvals_submit_parser.set_defaults(handler=_approvals_submit)

    approvals_show_parser = approvals_subparsers.add_parser("show", help="Show an approval request")
    approvals_show_parser.add_argument("approval_id", help="Approval id")
    approvals_show_parser.add_argument(
        "--store-path",
        default=DEFAULT_APPROVAL_STORE_PATH,
        help="Local JSON approval store path",
    )
    approvals_show_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    approvals_show_parser.set_defaults(handler=_approvals_show)

    approvals_approve_parser = approvals_subparsers.add_parser("approve", help="Approve a request")
    approvals_approve_parser.add_argument("approval_id", help="Approval id")
    approvals_approve_parser.add_argument("--decided-by", required=True, help="Decision maker")
    approvals_approve_parser.add_argument("--reason", default=None, help="Decision reason")
    approvals_approve_parser.add_argument(
        "--store-path",
        default=DEFAULT_APPROVAL_STORE_PATH,
        help="Local JSON approval store path",
    )
    approvals_approve_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    approvals_approve_parser.set_defaults(handler=_approvals_approve)

    approvals_reject_parser = approvals_subparsers.add_parser("reject", help="Reject a request")
    approvals_reject_parser.add_argument("approval_id", help="Approval id")
    approvals_reject_parser.add_argument("--decided-by", required=True, help="Decision maker")
    approvals_reject_parser.add_argument("--reason", default=None, help="Decision reason")
    approvals_reject_parser.add_argument(
        "--store-path",
        default=DEFAULT_APPROVAL_STORE_PATH,
        help="Local JSON approval store path",
    )
    approvals_reject_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    approvals_reject_parser.set_defaults(handler=_approvals_reject)

    approvals_modify_parser = approvals_subparsers.add_parser("modify", help="Approve with modifications")
    approvals_modify_parser.add_argument("approval_id", help="Approval id")
    approvals_modify_parser.add_argument("--decided-by", required=True, help="Decision maker")
    approvals_modify_parser.add_argument("--modifications-json", required=True, help="Modification JSON object")
    approvals_modify_parser.add_argument("--reason", default=None, help="Decision reason")
    approvals_modify_parser.add_argument(
        "--store-path",
        default=DEFAULT_APPROVAL_STORE_PATH,
        help="Local JSON approval store path",
    )
    approvals_modify_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    approvals_modify_parser.set_defaults(handler=_approvals_modify)

    memory_parser = subparsers.add_parser("memory", help="Search and manage memory")
    memory_subparsers = memory_parser.add_subparsers(dest="memory_command", required=True)
    memory_search_parser = memory_subparsers.add_parser("search", help="Search vector memory")
    memory_search_parser.add_argument("query", help="Search query text")
    memory_search_parser.add_argument(
        "--collection",
        default=DEFAULT_MEMORY_COLLECTION,
        help="Vector memory collection",
    )
    memory_search_parser.add_argument("--limit", type=int, default=5, help="Maximum results")
    memory_search_parser.add_argument(
        "--filter",
        dest="filters",
        action="append",
        default=[],
        help="Exact-match payload filter as key=value; can be repeated",
    )
    memory_search_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    memory_search_parser.set_defaults(handler=_memory_search)

    memory_reindex_parser = memory_subparsers.add_parser(
        "reindex",
        help="Rebuild vector memory from persisted run artifacts",
    )
    memory_reindex_parser.add_argument("--run-id", required=True, help="Run id to reindex")
    memory_reindex_parser.add_argument("--topic", default=None, help="Override memory topic")
    memory_reindex_parser.add_argument(
        "--artifact-root",
        default=".newsroom/runs",
        help="Directory where run artifacts are stored",
    )
    memory_reindex_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    memory_reindex_parser.set_defaults(handler=_memory_reindex)

    memory_bootstrap_parser = memory_subparsers.add_parser(
        "bootstrap",
        help="Create expected Qdrant vector memory collections",
    )
    memory_bootstrap_parser.add_argument(
        "--collection",
        dest="collections",
        action="append",
        default=[],
        help="Collection to bootstrap; repeat to override defaults",
    )
    memory_bootstrap_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    memory_bootstrap_parser.set_defaults(handler=_memory_bootstrap)

    diagnose_parser = subparsers.add_parser("diagnose", help="Run local diagnostics")
    diagnose_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    diagnose_parser.set_defaults(handler=_diagnose)

    storage_parser = subparsers.add_parser("storage", help="Inspect local storage")
    storage_subparsers = storage_parser.add_subparsers(dest="storage_command", required=True)

    storage_metrics_parser = storage_subparsers.add_parser("metrics", help="Show local storage metrics")
    storage_metrics_parser.add_argument(
        "--artifact-root",
        default=".newsroom/runs",
        help="Directory where run artifacts are stored",
    )
    storage_metrics_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    storage_metrics_parser.set_defaults(handler=_storage_metrics)

    storage_migrate_parser = storage_subparsers.add_parser(
        "migrate",
        help="Run configured persistence migrations",
    )
    storage_migrate_parser.add_argument(
        "--artifact-root",
        default=".newsroom/runs",
        help="Directory where local fallback records are stored",
    )
    storage_migrate_parser.add_argument(
        "--require-postgres",
        action="store_true",
        help="Fail if NEWS_DATABASE_DSN is not configured",
    )
    storage_migrate_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    storage_migrate_parser.set_defaults(handler=_storage_migrate)

    storage_backup_parser = storage_subparsers.add_parser(
        "backup",
        help="Create and restore local artifact backups",
    )
    storage_backup_subparsers = storage_backup_parser.add_subparsers(
        dest="storage_backup_command",
        required=True,
    )

    storage_backup_create_parser = storage_backup_subparsers.add_parser(
        "create",
        help="Create a local artifact backup",
    )
    _add_storage_backup_arguments(storage_backup_create_parser)
    storage_backup_create_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing backup archive",
    )
    storage_backup_create_parser.add_argument("--now", default=None, help="Optional current time as ISO datetime")
    storage_backup_create_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    storage_backup_create_parser.set_defaults(handler=_storage_backup_create)

    storage_backup_restore_parser = storage_backup_subparsers.add_parser(
        "restore",
        help="Restore a local artifact backup",
    )
    _add_storage_backup_arguments(storage_backup_restore_parser)
    storage_backup_restore_parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm writing backed-up files",
    )
    storage_backup_restore_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing restored files",
    )
    storage_backup_restore_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    storage_backup_restore_parser.set_defaults(handler=_storage_backup_restore)

    storage_lineage_parser = storage_subparsers.add_parser(
        "lineage",
        help="Query local lineage records",
    )
    storage_lineage_subparsers = storage_lineage_parser.add_subparsers(
        dest="storage_lineage_command",
        required=True,
    )

    storage_lineage_list_parser = storage_lineage_subparsers.add_parser(
        "list",
        help="List lineage refs for a run",
    )
    _add_storage_lineage_base_arguments(storage_lineage_list_parser)
    storage_lineage_list_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    storage_lineage_list_parser.set_defaults(handler=_storage_lineage_list)

    storage_lineage_upstream_parser = storage_lineage_subparsers.add_parser(
        "upstream",
        help="List upstream lineage refs for a target",
    )
    _add_storage_lineage_base_arguments(storage_lineage_upstream_parser)
    storage_lineage_upstream_parser.add_argument("--target-type", required=True, help="Target record type")
    storage_lineage_upstream_parser.add_argument("--target-id", required=True, help="Target record id")
    storage_lineage_upstream_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    storage_lineage_upstream_parser.set_defaults(handler=_storage_lineage_upstream)

    storage_lineage_downstream_parser = storage_lineage_subparsers.add_parser(
        "downstream",
        help="List downstream lineage refs for a source",
    )
    _add_storage_lineage_base_arguments(storage_lineage_downstream_parser)
    storage_lineage_downstream_parser.add_argument("--source-type", required=True, help="Source record type")
    storage_lineage_downstream_parser.add_argument("--source-id", required=True, help="Source record id")
    storage_lineage_downstream_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    storage_lineage_downstream_parser.set_defaults(handler=_storage_lineage_downstream)

    storage_retention_parser = storage_subparsers.add_parser(
        "retention",
        help="Plan and apply local artifact retention",
    )
    storage_retention_subparsers = storage_retention_parser.add_subparsers(
        dest="storage_retention_command",
        required=True,
    )

    storage_retention_plan_parser = storage_retention_subparsers.add_parser(
        "plan",
        help="Plan local artifact retention",
    )
    _add_storage_retention_arguments(storage_retention_plan_parser)
    storage_retention_plan_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    storage_retention_plan_parser.set_defaults(handler=_storage_retention_plan)

    storage_retention_apply_parser = storage_retention_subparsers.add_parser(
        "apply",
        help="Delete expired local artifacts",
    )
    _add_storage_retention_arguments(storage_retention_apply_parser)
    storage_retention_apply_parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm deletion of expired artifacts",
    )
    storage_retention_apply_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    storage_retention_apply_parser.set_defaults(handler=_storage_retention_apply)

    sources_parser = subparsers.add_parser("sources", help="Inspect source registry and health")
    sources_subparsers = sources_parser.add_subparsers(dest="sources_command", required=True)

    sources_list_parser = sources_subparsers.add_parser("list", help="List registered sources")
    sources_list_parser.add_argument("--include-disabled", action="store_true", help="Include disabled sources")
    sources_list_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    sources_list_parser.set_defaults(handler=_sources_list)

    sources_arxiv_parser = sources_subparsers.add_parser("arxiv", help="Fetch arXiv source items")
    sources_arxiv_parser.add_argument("--query", required=True, help="arXiv search query")
    sources_arxiv_parser.add_argument("--limit", type=int, default=5, help="Maximum paper entries")
    sources_arxiv_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    sources_arxiv_parser.set_defaults(handler=_sources_arxiv)

    sources_github_parser = sources_subparsers.add_parser("github", help="Fetch GitHub release items")
    sources_github_parser.add_argument("--repo", required=True, help="GitHub repository as owner/repo")
    sources_github_parser.add_argument("--limit", type=int, default=5, help="Maximum releases")
    sources_github_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    sources_github_parser.set_defaults(handler=_sources_github)

    sources_health_parser = sources_subparsers.add_parser("health", help="Show source health")
    sources_health_parser.add_argument("--include-disabled", action="store_true", help="Include disabled sources")
    sources_health_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    sources_health_parser.set_defaults(handler=_sources_health)

    sources_check_health_parser = sources_subparsers.add_parser(
        "check-health",
        help="Probe configured sources and update source health",
    )
    sources_check_health_parser.add_argument("--source-id", default=None, help="Optional source id to check")
    sources_check_health_parser.add_argument("--include-disabled", action="store_true", help="Include disabled sources")
    sources_check_health_parser.add_argument("--limit", type=int, default=None, help="Maximum sources to check")
    sources_check_health_parser.add_argument("--force", action="store_true", help="Probe even during cooldown")
    sources_check_health_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    sources_check_health_parser.set_defaults(handler=_sources_check_health)

    sources_validate_parser = sources_subparsers.add_parser("validate", help="Validate source registry")
    sources_validate_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    sources_validate_parser.set_defaults(handler=_sources_validate)

    runs_parser = subparsers.add_parser("runs", help="Inspect workflow run history")
    runs_subparsers = runs_parser.add_subparsers(dest="runs_command", required=True)

    runs_list_parser = runs_subparsers.add_parser("list", help="List local runs")
    runs_list_parser.add_argument("--limit", type=int, default=20, help="Maximum runs")
    runs_list_parser.add_argument(
        "--artifact-root",
        default=".newsroom/runs",
        help="Directory where run artifacts are stored",
    )
    runs_list_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    runs_list_parser.set_defaults(handler=_runs_list)

    runs_show_parser = runs_subparsers.add_parser("show", help="Show a local run manifest")
    runs_show_parser.add_argument("run_id", help="Run id")
    runs_show_parser.add_argument(
        "--artifact-root",
        default=".newsroom/runs",
        help="Directory where run artifacts are stored",
    )
    runs_show_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    runs_show_parser.set_defaults(handler=_runs_show)

    runs_events_parser = runs_subparsers.add_parser("events", help="Show local run events")
    runs_events_parser.add_argument("run_id", help="Run id")
    runs_events_parser.add_argument(
        "--artifact-root",
        default=".newsroom/runs",
        help="Directory where run artifacts are stored",
    )
    runs_events_parser.add_argument("--limit", type=int, default=None, help="Maximum events")
    runs_events_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    runs_events_parser.set_defaults(handler=_runs_events)

    runs_replay_parser = runs_subparsers.add_parser("replay", help="Build a run replay bundle")
    runs_replay_parser.add_argument("run_id", help="Run id")
    runs_replay_parser.add_argument(
        "--artifact-root",
        default=".newsroom/runs",
        help="Directory where run artifacts are stored",
    )
    runs_replay_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    runs_replay_parser.set_defaults(handler=_runs_replay)

    artifacts_parser = subparsers.add_parser("artifacts", help="Inspect run artifacts")
    artifacts_subparsers = artifacts_parser.add_subparsers(dest="artifacts_command", required=True)

    artifacts_list_parser = artifacts_subparsers.add_parser("list", help="List artifacts for a run")
    artifacts_list_parser.add_argument("--run-id", required=True, help="Run id")
    artifacts_list_parser.add_argument(
        "--artifact-root",
        default=".newsroom/runs",
        help="Directory where run artifacts are stored",
    )
    artifacts_list_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    artifacts_list_parser.set_defaults(handler=_artifacts_list)

    artifacts_show_parser = artifacts_subparsers.add_parser("show", help="Show a run artifact")
    artifacts_show_parser.add_argument("--run-id", required=True, help="Run id")
    artifacts_show_parser.add_argument("--artifact-key", required=True, help="Artifact key from manifest")
    artifacts_show_parser.add_argument(
        "--artifact-root",
        default=".newsroom/runs",
        help="Directory where run artifacts are stored",
    )
    artifacts_show_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    artifacts_show_parser.set_defaults(handler=_artifacts_show)

    tools_parser = subparsers.add_parser("tools", help="Discover Tool Runtime tools")
    tools_subparsers = tools_parser.add_subparsers(dest="tools_command", required=True)

    tools_list_parser = tools_subparsers.add_parser("list", help="List built-in tool catalog")
    _add_tool_policy_args(tools_list_parser)
    tools_list_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    tools_list_parser.set_defaults(handler=_tools_list)

    tools_schema_parser = tools_subparsers.add_parser(
        "schema",
        help="Export built-in tool schemas after applying a tool policy",
    )
    _add_tool_policy_args(tools_schema_parser)
    tools_schema_parser.add_argument("--agent-id", default="cli", help="Agent id for policy export")
    tools_schema_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    tools_schema_parser.set_defaults(handler=_tools_schema)

    mcp_parser = subparsers.add_parser("mcp", help="Inspect inbound MCP catalog and tools")
    mcp_subparsers = mcp_parser.add_subparsers(dest="mcp_command", required=True)

    mcp_catalog_parser = mcp_subparsers.add_parser("catalog", help="Show MCP tools/resources/prompts")
    mcp_catalog_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    mcp_catalog_parser.set_defaults(handler=_mcp_catalog)

    mcp_call_parser = mcp_subparsers.add_parser("call", help="Call an MCP tool locally")
    mcp_call_parser.add_argument("tool_name", help="MCP tool name")
    mcp_call_parser.add_argument("--args-json", default="{}", help="Tool arguments as a JSON object")
    mcp_call_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    mcp_call_parser.set_defaults(handler=_mcp_call)

    mcp_read_resource_parser = mcp_subparsers.add_parser("read-resource", help="Read an MCP resource locally")
    mcp_read_resource_parser.add_argument("uri", help="MCP resource URI")
    mcp_read_resource_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    mcp_read_resource_parser.set_defaults(handler=_mcp_read_resource)

    mcp_get_prompt_parser = mcp_subparsers.add_parser("get-prompt", help="Get an MCP prompt locally")
    mcp_get_prompt_parser.add_argument("prompt_name", help="MCP prompt name")
    mcp_get_prompt_parser.add_argument("--args-json", default="{}", help="Prompt arguments as a JSON object")
    mcp_get_prompt_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    mcp_get_prompt_parser.set_defaults(handler=_mcp_get_prompt)

    mcp_serve_parser = mcp_subparsers.add_parser("serve-stdio", help="Run MCP stdio adapter")
    mcp_serve_parser.set_defaults(handler=_mcp_serve_stdio)

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

    live_smoke_parser = dev_subparsers.add_parser(
        "run-live-smoke",
        help="Run real live workflow smoke when live credentials are configured",
    )
    live_smoke_parser.add_argument("--topic", default="AI", help="Topic for the live smoke report")
    live_smoke_parser.add_argument("--source-limit", type=int, default=3, help="Maximum source items")
    live_smoke_parser.add_argument(
        "--artifact-root",
        default=".newsroom/runs",
        help="Directory where run artifacts are written",
    )
    live_smoke_parser.add_argument("--run-id", default=None, help="Optional deterministic run id")
    live_smoke_parser.add_argument(
        "--fail-if-unready",
        action="store_true",
        help="Return failure instead of skipped when live readiness checks are not configured",
    )
    live_smoke_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    live_smoke_parser.set_defaults(handler=_run_live_smoke)
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


def _run_live_smoke(args: argparse.Namespace) -> int:
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


def _run_daily(args: argparse.Namespace) -> int:
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


def _run_weekly(args: argparse.Namespace) -> int:
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
        print(f"profile=weekly")
        print(f"artifact_dir={result.artifact_dir}")
        print(f"manifest={result.manifest_path}")
        print(f"events={result.events_path}")
        if result.error:
            print(f"error={result.error.get('message')}")

    return 0 if result.status == WorkflowStatus.SUCCEEDED else 1


def _latest_report(args: argparse.Namespace) -> int:
    service = ReportApplicationService(artifact_root=args.artifact_root)
    try:
        record = service.latest_report()
    except FileNotFoundError as exc:
        print(str(exc))
        return 1

    if args.format == "json":
        print(json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True))
    else:
        print(record.report_markdown or json.dumps(record.report_json, ensure_ascii=False, indent=2))
    return 0


def _reports_search(args: argparse.Namespace) -> int:
    try:
        result = ReportApplicationService(artifact_root=args.artifact_root).search_reports(
            query=args.query,
            limit=args.limit,
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"report_count={payload['report_count']}")
        for report in payload["reports"]:
            print(f"- {report['run_id']} title={report['title']} finished_at={report['finished_at']}")
    return 0


def _reports_list(args: argparse.Namespace) -> int:
    try:
        result = ReportApplicationService(artifact_root=args.artifact_root).list_reports(
            limit=args.limit,
            workflow_id=args.workflow_id,
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"report_count={payload['report_count']}")
        for report in payload["reports"]:
            print(
                f"- {report['run_id']} workflow={report.get('workflow_id')} "
                f"title={report['title']} finished_at={report['finished_at']}"
            )
    return 0


def _reports_show(args: argparse.Namespace) -> int:
    try:
        record = ReportApplicationService(artifact_root=args.artifact_root).get_report(args.report_id)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc))
        return 1
    payload = record.to_dict()
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(record.report_markdown or json.dumps(record.report_json, ensure_ascii=False, indent=2))
    return 0


def _subscriptions_create(args: argparse.Namespace) -> int:
    try:
        subscription = SubscriptionApplicationService(store_path=args.store_path).create_topic_subscription(
            topic=args.topic,
            cadence=args.cadence,
            profile=args.profile,
            source_limit=args.source_limit,
            subscription_id=args.subscription_id,
            enabled=not args.disabled,
            metadata=_parse_key_values(args.metadata or []),
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    return _print_subscription(subscription.to_dict(), json_output=args.json)


def _subscriptions_list(args: argparse.Namespace) -> int:
    try:
        result = SubscriptionApplicationService(store_path=args.store_path).list_topic_subscriptions(
            enabled_only=args.enabled_only,
            cadence=args.cadence,
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"subscription_count={payload['subscription_count']}")
        for item in payload["subscriptions"]:
            state = "enabled" if item["enabled"] else "disabled"
            print(f"- {item['subscription_id']} {state} cadence={item['cadence']} topic={item['topic']}")
    return 0


def _subscriptions_enable(args: argparse.Namespace) -> int:
    return _subscriptions_set_enabled(args, enabled=True)


def _subscriptions_disable(args: argparse.Namespace) -> int:
    return _subscriptions_set_enabled(args, enabled=False)


def _subscriptions_set_enabled(args: argparse.Namespace, *, enabled: bool) -> int:
    try:
        subscription = SubscriptionApplicationService(store_path=args.store_path).set_enabled(
            args.subscription_id,
            enabled=enabled,
        )
    except (KeyError, ValueError) as exc:
        print(str(exc))
        return 1
    return _print_subscription(subscription.to_dict(), json_output=args.json)


def _subscriptions_delete(args: argparse.Namespace) -> int:
    deleted = SubscriptionApplicationService(store_path=args.store_path).delete_topic_subscription(
        args.subscription_id,
    )
    payload = {"subscription_id": args.subscription_id, "deleted": deleted}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"deleted={str(deleted).lower()}")
    return 0


def _print_subscription(payload: dict, *, json_output: bool) -> int:
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        state = "enabled" if payload["enabled"] else "disabled"
        print(f"subscription_id={payload['subscription_id']}")
        print(f"topic={payload['topic']}")
        print(f"cadence={payload['cadence']}")
        print(f"state={state}")
    return 0


def _entities_create(args: argparse.Namespace) -> int:
    try:
        entity = EntityTrackingApplicationService(store_path=args.store_path).create_entity(
            name=args.name,
            kind=args.kind,
            aliases=args.alias or [],
            entity_id=args.entity_id,
            enabled=not args.disabled,
            metadata=_parse_key_values(args.metadata or []),
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    return _print_entity(entity.to_dict(), json_output=args.json)


def _entities_list(args: argparse.Namespace) -> int:
    try:
        result = EntityTrackingApplicationService(store_path=args.store_path).list_entities(
            enabled_only=args.enabled_only,
            kind=args.kind,
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"entity_count={payload['entity_count']}")
        for item in payload["entities"]:
            state = "enabled" if item["enabled"] else "disabled"
            print(f"- {item['entity_id']} {state} kind={item['kind']} name={item['name']}")
    return 0


def _entities_enable(args: argparse.Namespace) -> int:
    return _entities_set_enabled(args, enabled=True)


def _entities_disable(args: argparse.Namespace) -> int:
    return _entities_set_enabled(args, enabled=False)


def _entities_set_enabled(args: argparse.Namespace, *, enabled: bool) -> int:
    try:
        entity = EntityTrackingApplicationService(store_path=args.store_path).set_enabled(
            args.entity_id,
            enabled=enabled,
        )
    except (KeyError, ValueError) as exc:
        print(str(exc))
        return 1
    return _print_entity(entity.to_dict(), json_output=args.json)


def _entities_delete(args: argparse.Namespace) -> int:
    deleted = EntityTrackingApplicationService(store_path=args.store_path).delete_entity(args.entity_id)
    payload = {"entity_id": args.entity_id, "deleted": deleted}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"deleted={str(deleted).lower()}")
    return 0


def _entities_match_reports(args: argparse.Namespace) -> int:
    try:
        result = EntityTrackingApplicationService(store_path=args.store_path).match_reports(
            args.entity_id,
            artifact_root=args.artifact_root,
            limit=args.limit,
            workflow_id=args.workflow_id,
        )
    except (KeyError, ValueError) as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"match_count={payload['match_count']}")
        for item in payload["matches"]:
            aliases = ",".join(item["matched_aliases"])
            print(f"- {item['report_id']} aliases={aliases} title={item['title']}")
    return 0


def _print_entity(payload: dict, *, json_output: bool) -> int:
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        state = "enabled" if payload["enabled"] else "disabled"
        print(f"entity_id={payload['entity_id']}")
        print(f"name={payload['name']}")
        print(f"kind={payload['kind']}")
        print(f"state={state}")
    return 0


def _api_serve(args: argparse.Namespace) -> int:
    from interfaces.api.server import run_api_server

    try:
        run_api_server(
            host=args.host,
            port=args.port,
            reload=args.reload,
            log_level=args.log_level,
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    return 0


def _api_openapi(args: argparse.Namespace) -> int:
    from interfaces.api.schema import export_openapi_schema, summarize_openapi_schema

    schema = export_openapi_schema()
    if args.output:
        Path(args.output).write_text(
            json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.json or not args.output:
        payload = schema if args.json else summarize_openapi_schema(schema)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


def _worker_enqueue_daily(args: argparse.Namespace) -> int:
    service = WorkerApplicationService(redis_url=args.redis_url)
    result = service.enqueue_daily(
        profile=args.profile,
        topic=args.topic,
        source_limit=args.source_limit,
        run_id=args.run_id,
        queue_name=args.queue_name,
    )
    payload = result.to_dict()

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"task_id={payload['task_id']}")
        print(f"task_type={payload['task_type']}")
        print(f"queue_name={payload['queue_name']}")
        print(f"message_id={payload['message_id']}")
        print(f"profile={payload['profile']}")
        print(f"topic={payload['topic']}")
    return 0


def _worker_enqueue_memory_reindex(args: argparse.Namespace) -> int:
    service = WorkerApplicationService(redis_url=args.redis_url)
    result = service.enqueue_memory_reindex(
        run_id=args.run_id,
        topic=args.topic,
        queue_name=args.queue_name,
    )
    payload = result.to_dict()

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"task_id={payload['task_id']}")
        print(f"task_type={payload['task_type']}")
        print(f"queue_name={payload['queue_name']}")
        print(f"message_id={payload['message_id']}")
        print(f"run_id={payload['run_id']}")
        if payload["topic"]:
            print(f"topic={payload['topic']}")
    return 0


def _worker_enqueue_source_health(args: argparse.Namespace) -> int:
    service = WorkerApplicationService(redis_url=args.redis_url)
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
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"task_id={payload['task_id']}")
        print(f"task_type={payload['task_type']}")
        print(f"queue_name={payload['queue_name']}")
        print(f"message_id={payload['message_id']}")
    return 0


def _worker_run_once(args: argparse.Namespace) -> int:
    service = WorkerApplicationService(artifact_root=args.artifact_root, redis_url=args.redis_url)
    try:
        result = service.run_once(
            worker_id=args.worker_id,
            queue_names=args.queue_names or [DEFAULT_DAILY_QUEUE],
            block_ms=args.block_ms,
            reclaim_stale_ms=args.reclaim_stale_ms,
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
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
            print(f"workflow_run_id={payload['workflow_run_id']}")
            if payload["error_message"]:
                print(f"error={payload['error_message']}")
    return 0 if result.success is not False else 1


def _worker_run(args: argparse.Namespace) -> int:
    service = WorkerApplicationService(artifact_root=args.artifact_root, redis_url=args.redis_url)
    try:
        result = service.run_loop(
            worker_id=args.worker_id,
            queue_names=args.queue_names or [DEFAULT_DAILY_QUEUE],
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
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"worker_id={payload['worker_id']}")
        print(f"stop_reason={payload['stop_reason']}")
        print(f"iterations={payload['iterations']}")
        print(f"processed_count={payload['processed_count']}")
        print(f"succeeded_count={payload['succeeded_count']}")
        print(f"failed_count={payload['failed_count']}")
        print(f"idle_count={payload['idle_count']}")
    return 0 if payload["failed_count"] == 0 else 1


def _worker_heartbeat(args: argparse.Namespace) -> int:
    service = WorkerApplicationService(redis_url=args.redis_url)
    result = service.record_heartbeat(
        worker_id=args.worker_id,
        queue_names=args.queue_names or [DEFAULT_DAILY_QUEUE],
        status=args.status,
        current_task_id=args.current_task_id,
    )
    payload = result.to_dict()

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        worker = payload["worker"]
        print(f"worker_id={worker['worker_id']}")
        print(f"status={worker['status']}")
        print(f"stale={str(worker['stale']).lower()}")
        print(f"last_heartbeat_at={worker['last_heartbeat_at']}")
    return 0


def _worker_status(args: argparse.Namespace) -> int:
    try:
        result = WorkerApplicationService(redis_url=args.redis_url).list_worker_status(
            worker_id=args.worker_id,
            stale_after_seconds=args.stale_after_seconds,
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"worker_count={payload['worker_count']}")
        print(f"unhealthy_count={payload['unhealthy_count']}")
        for worker in payload["workers"]:
            print(
                f"- {worker['worker_id']} status={worker['status']} "
                f"stale={str(worker['stale']).lower()} heartbeat={worker['last_heartbeat_at']}"
            )
    return 0


def _worker_queues(args: argparse.Namespace) -> int:
    result = WorkerApplicationService(redis_url=args.redis_url).queue_status(
        queue_names=args.queue_names
        or [DEFAULT_DAILY_QUEUE, DEFAULT_MEMORY_QUEUE, DEFAULT_DEAD_LETTER_QUEUE]
    )
    payload = result.to_dict()

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
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


def _schedules_list(args: argparse.Namespace) -> int:
    result = ScheduleApplicationService(store_path=args.store_path).list_schedules(
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


def _schedules_add_daily(args: argparse.Namespace) -> int:
    if args.trigger_type == "interval" and args.interval_seconds <= 0:
        raise SystemExit("--interval-seconds must be greater than zero")
    run_at = _parse_cli_datetime(args.run_at)
    spec = ScheduleSpec(
        schedule_id=args.schedule_id,
        name=args.name,
        trigger_type=args.trigger_type,
        task_type="daily_intelligence.run",
        payload_template={
            "profile": args.profile,
            "topic": args.topic,
            "source_limit": args.source_limit,
        },
        queue_name=args.queue_name,
        interval_seconds=args.interval_seconds if args.trigger_type == "interval" else None,
        run_at=run_at if args.trigger_type == "interval" else None,
    )
    record = ScheduleRecord(spec=spec, next_run_at=spec.run_at)
    result = ScheduleApplicationService(store_path=args.store_path).upsert_schedule(record)
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


def _schedules_tick(args: argparse.Namespace) -> int:
    result = ScheduleApplicationService(
        store_path=args.store_path,
        redis_url=args.redis_url,
    ).tick(
        now=_parse_cli_datetime(args.now),
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


def _schedules_run(args: argparse.Namespace) -> int:
    try:
        result = ScheduleApplicationService(
            store_path=args.store_path,
            redis_url=args.redis_url,
        ).run_loop(
            now=_parse_cli_datetime(args.now),
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


def _schedules_trigger(args: argparse.Namespace) -> int:
    result = ScheduleApplicationService(
        store_path=args.store_path,
        redis_url=args.redis_url,
    ).trigger_manual(
        args.schedule_id,
        now=_parse_cli_datetime(args.now),
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


def _approvals_list(args: argparse.Namespace) -> int:
    result = ApprovalApplicationService(store_path=args.store_path).list_approvals(status=args.status)
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"approval_count={payload['approval_count']}")
        for approval in payload["approvals"]:
            print(
                f"- {approval['approval_id']} status={approval['status']} "
                f"action={approval['requested_action']} risk={approval['risk_level']}"
            )
    return 0


def _approvals_submit(args: argparse.Namespace) -> int:
    result = ApprovalApplicationService(store_path=args.store_path).submit_request(
        requested_action=args.requested_action,
        risk_level=args.risk_level,
        reason=args.reason,
        payload=_parse_json_object(args.payload_json),
        task_id=args.task_id,
        run_id=args.run_id,
        requested_by=args.requested_by,
        expires_at=_parse_cli_datetime(args.expires_at),
        metadata=_parse_json_object(args.metadata_json),
    )
    _print_approval_detail(result.to_dict(), json_output=args.json)
    return 0


def _approvals_show(args: argparse.Namespace) -> int:
    try:
        result = ApprovalApplicationService(store_path=args.store_path).get_approval(args.approval_id)
    except ApprovalNotFoundError as exc:
        print(str(exc))
        return 1
    _print_approval_detail(result.to_dict(), json_output=args.json)
    return 0


def _approvals_approve(args: argparse.Namespace) -> int:
    return _approval_decision(
        args,
        lambda service: service.approve(
            args.approval_id,
            decided_by=args.decided_by,
            reason=args.reason,
        ),
    )


def _approvals_reject(args: argparse.Namespace) -> int:
    return _approval_decision(
        args,
        lambda service: service.reject(
            args.approval_id,
            decided_by=args.decided_by,
            reason=args.reason,
        ),
    )


def _approvals_modify(args: argparse.Namespace) -> int:
    return _approval_decision(
        args,
        lambda service: service.modify(
            args.approval_id,
            decided_by=args.decided_by,
            modifications=_parse_json_object(args.modifications_json),
            reason=args.reason,
        ),
    )


def _approval_decision(args: argparse.Namespace, call) -> int:
    try:
        result = call(ApprovalApplicationService(store_path=args.store_path))
    except (ApprovalNotFoundError, ApprovalAlreadyDecidedError, ValueError) as exc:
        print(str(exc))
        return 1
    _print_approval_detail(result.to_dict(), json_output=args.json)
    return 0


def _print_approval_detail(payload: dict, *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return
    approval = payload["approval"]
    print(f"approval_id={approval['approval_id']}")
    print(f"status={approval['status']}")
    print(f"requested_action={approval['requested_action']}")
    print(f"risk_level={approval['risk_level']}")


def _memory_search(args: argparse.Namespace) -> int:
    filters = _parse_filters(args.filters)
    result = MemoryApplicationService().search(
        text=args.query,
        collection=args.collection,
        limit=args.limit,
        filters=filters,
    )
    payload = result.to_dict()

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"collection={payload['collection']}")
        print(f"query={payload['query']}")
        print(f"result_count={payload['result_count']}")
        for item in payload["results"]:
            print(f"- {item['document_id']} score={item['score']:.4f} source_type={item['source_type']}")
            if item.get("text"):
                print(f"  {item['text'][:160]}")
    return 0


def _memory_reindex(args: argparse.Namespace) -> int:
    try:
        result = MemoryApplicationService(artifact_root=args.artifact_root).reindex_run(
            args.run_id,
            topic=args.topic,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"run_id={payload['run_id']}")
        print(f"topic={payload['topic']}")
        print(f"documents_indexed={payload['documents_indexed']}")
        print(f"collections={','.join(payload['collections'])}")
    return 0


def _memory_bootstrap(args: argparse.Namespace) -> int:
    try:
        result = MemoryApplicationService().bootstrap_collections(
            collections=args.collections or None,
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"collection_count={payload['collection_count']}")
        print(f"created_count={payload['created_count']}")
        print(f"existing_count={payload['existing_count']}")
        for item in payload["collections"]:
            state = "created" if item["created"] else "existing"
            print(f"- {item['collection']} {state} vector_size={item['vector_size']}")
    return 0


def _parse_filters(values: list[str]) -> dict[str, str]:
    filters: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"invalid filter '{value}', expected key=value")
        key, filter_value = value.split("=", 1)
        if not key:
            raise SystemExit(f"invalid filter '{value}', expected key=value")
        filters[key] = filter_value
    return filters


def _parse_key_values(values: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"invalid metadata '{value}', expected key=value")
        key, parsed_value = value.split("=", 1)
        if not key:
            raise ValueError(f"invalid metadata '{value}', expected key=value")
        parsed[key] = parsed_value
    return parsed


def _add_storage_backup_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--artifact-root",
        default=".newsroom/runs",
        help="Directory where run artifacts are stored",
    )
    parser.add_argument("--backup-path", required=True, help="Backup archive path")


def _add_storage_lineage_base_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--artifact-root",
        default=".newsroom/runs",
        help="Directory where run artifacts are stored",
    )
    parser.add_argument("--run-id", required=True, help="Workflow run id")


def _add_storage_retention_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--artifact-root",
        default=".newsroom/runs",
        help="Directory where run artifacts are stored",
    )
    parser.add_argument("--run-id", default=None, help="Optional run id filter")
    parser.add_argument("--now", default=None, help="Optional current time as ISO datetime")
    parser.add_argument("--raw-source-retention-days", type=int, default=None)
    parser.add_argument("--llm-artifact-retention-days", type=int, default=None)
    parser.add_argument("--run-artifact-retention-days", type=int, default=None)
    parser.add_argument("--report-retention-days", type=int, default=None)
    parser.add_argument("--evidence-retention-days", type=int, default=None)
    parser.add_argument("--vector-retention-days", type=int, default=None)


def _retention_policy_from_args(args: argparse.Namespace) -> RetentionPolicy:
    payload = {}
    for name in [
        "raw_source_retention_days",
        "llm_artifact_retention_days",
        "run_artifact_retention_days",
        "report_retention_days",
        "evidence_retention_days",
        "vector_retention_days",
    ]:
        value = getattr(args, name)
        if value is not None:
            payload[name] = value
    return RetentionPolicy.from_dict(payload)


def _diagnose(args: argparse.Namespace) -> int:
    result = DiagnosticApplicationService().run()
    payload = result.to_dict()

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"status={payload['status']}")
        print(f"summary={payload['summary']}")
        for check in payload["checks"]:
            print(f"[{check['status'].upper()}] {check['name']}: {check['message']}")
            if check.get("remediation"):
                print(f"  fix={check['remediation']}")
    return 0 if result.status != "error" else 1


def _storage_metrics(args: argparse.Namespace) -> int:
    payload = StorageApplicationService(args.artifact_root).metrics().to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"runs_count={payload['runs_count']}")
        print(f"reports_count={payload['reports_count']}")
        print(f"artifacts_count={payload['artifacts_count']}")
        print(f"artifact_bytes_total={payload['artifact_bytes_total']}")
        print(f"events_count={payload['events_count']}")
        print(f"lineage_refs_count={payload['lineage_refs_count']}")
    return 0


def _storage_migrate(args: argparse.Namespace) -> int:
    try:
        result = StorageApplicationService(args.artifact_root).migrate_persistence(
            require_postgres=args.require_postgres
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"migrated={str(payload['migrated']).lower()}")
        print(f"backend={payload['backend']}")
        print(f"postgres_required={str(payload['postgres_required']).lower()}")
    return 0


def _storage_backup_create(args: argparse.Namespace) -> int:
    try:
        result = StorageApplicationService(args.artifact_root).create_backup(
            args.backup_path,
            overwrite=args.overwrite,
            now=_parse_cli_datetime(args.now),
        )
    except (FileNotFoundError, FileExistsError, ValueError) as exc:
        print(str(exc))
        return 1
    _print_storage_backup_result(result.to_dict(), json_output=args.json, count_key="file_count")
    return 0


def _storage_backup_restore(args: argparse.Namespace) -> int:
    if not args.yes:
        print("backup restore requires --yes")
        return 1
    try:
        result = StorageApplicationService(args.artifact_root).restore_backup(
            args.backup_path,
            overwrite=args.overwrite,
        )
    except (FileNotFoundError, FileExistsError, ValueError) as exc:
        print(str(exc))
        return 1
    _print_storage_backup_result(result.to_dict(), json_output=args.json, count_key="restored_count")
    return 0


def _print_storage_backup_result(
    payload: dict,
    *,
    json_output: bool,
    count_key: str,
) -> None:
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return
    print(f"artifact_root={payload['artifact_root']}")
    print(f"backup_path={payload['backup_path']}")
    print(f"{count_key}={payload[count_key]}")
    print(f"total_bytes={payload['total_bytes']}")


def _storage_lineage_list(args: argparse.Namespace) -> int:
    try:
        result = StorageApplicationService(args.artifact_root).list_lineage(args.run_id)
    except ValueError as exc:
        print(str(exc))
        return 1
    _print_storage_lineage_result(result.to_dict(), json_output=args.json)
    return 0


def _storage_lineage_upstream(args: argparse.Namespace) -> int:
    try:
        result = StorageApplicationService(args.artifact_root).lineage_upstream(
            run_id=args.run_id,
            target_type=args.target_type,
            target_id=args.target_id,
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    _print_storage_lineage_result(result.to_dict(), json_output=args.json)
    return 0


def _storage_lineage_downstream(args: argparse.Namespace) -> int:
    try:
        result = StorageApplicationService(args.artifact_root).lineage_downstream(
            run_id=args.run_id,
            source_type=args.source_type,
            source_id=args.source_id,
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    _print_storage_lineage_result(result.to_dict(), json_output=args.json)
    return 0


def _print_storage_lineage_result(payload: dict, *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return
    print(f"artifact_root={payload['artifact_root']}")
    print(f"run_id={payload['run_id']}")
    print(f"query_type={payload['query_type']}")
    print(f"lineage_count={payload['lineage_count']}")
    for ref in payload["lineage_refs"]:
        print(
            f"- {ref['source_type']}:{ref['source_id']} -> "
            f"{ref['target_type']}:{ref['target_id']} relation={ref['relation_type']}"
        )


def _storage_retention_plan(args: argparse.Namespace) -> int:
    try:
        result = StorageApplicationService(args.artifact_root).plan_retention(
            policy=_retention_policy_from_args(args),
            run_id=args.run_id,
            now=_parse_cli_datetime(args.now),
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    _print_storage_retention_result(result.to_dict(), json_output=args.json)
    return 0


def _storage_retention_apply(args: argparse.Namespace) -> int:
    if not args.yes:
        print("retention apply requires --yes")
        return 1
    try:
        result = StorageApplicationService(args.artifact_root).apply_retention(
            policy=_retention_policy_from_args(args),
            run_id=args.run_id,
            now=_parse_cli_datetime(args.now),
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        _print_storage_retention_result(payload, json_output=False)
        print(f"deleted_count={payload['deleted_count']}")
    return 0


def _print_storage_retention_result(payload: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return
    print(f"artifact_root={payload['artifact_root']}")
    if payload["run_id"]:
        print(f"run_id={payload['run_id']}")
    print(f"artifact_count={payload['artifact_count']}")
    print(f"delete_count={payload['delete_count']}")
    print(f"keep_count={payload['keep_count']}")


def _sources_list(args: argparse.Namespace) -> int:
    result = SourceApplicationService().list_sources(enabled_only=not args.include_disabled)
    payload = result.to_dict()

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"source_count={payload['source_count']}")
        for source in payload["sources"]:
            print(
                f"- {source['source_id']} type={source['source_type']} "
                f"reliability={source['reliability']} enabled={str(source['enabled']).lower()}"
            )
            print(f"  {source['name']} <{source['url']}>")
    return 0


def _sources_arxiv(args: argparse.Namespace) -> int:
    try:
        result = SourceApplicationService().fetch_arxiv(query=args.query, limit=args.limit)
    except ValueError as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"item_count={payload['item_count']}")
        print(f"error_count={payload['error_count']}")
        for item in payload["items"]:
            print(f"- {item['title']} <{item['url']}>")
        for error in payload["errors"]:
            print(f"error={error['error_type']}: {error['error_message']}")
    return 0 if payload["error_count"] == 0 else 1


def _sources_github(args: argparse.Namespace) -> int:
    try:
        result = SourceApplicationService().fetch_github_releases(
            repository=args.repo,
            limit=args.limit,
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"item_count={payload['item_count']}")
        print(f"error_count={payload['error_count']}")
        for item in payload["items"]:
            print(f"- {item['title']} <{item['url']}>")
        for error in payload["errors"]:
            print(f"error={error['error_type']}: {error['error_message']}")
    return 0 if payload["error_count"] == 0 else 1


def _sources_health(args: argparse.Namespace) -> int:
    result = SourceApplicationService().source_health(enabled_only=not args.include_disabled)
    payload = result.to_dict()

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"source_count={payload['source_count']}")
        for item in payload["health"]:
            print(
                f"- {item['source_id']} status={item['status']} "
                f"failures={item['consecutive_failures']} "
                f"success_24h={item.get('success_count_24h', 0)} "
                f"failure_24h={item.get('failure_count_24h', 0)} "
                f"avg_latency_ms_24h={item.get('avg_latency_ms_24h')}"
            )
    return 0


def _sources_check_health(args: argparse.Namespace) -> int:
    try:
        result = SourceApplicationService().check_source_health(
            source_id=args.source_id,
            enabled_only=not args.include_disabled,
            limit=args.limit,
            force=args.force,
        )
    except (KeyError, ValueError) as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"checked_count={payload['checked_count']}")
        print(f"succeeded_count={payload['succeeded_count']}")
        print(f"failed_count={payload['failed_count']}")
        print(f"skipped_count={payload['skipped_count']}")
        for entry in payload["entries"]:
            print(
                f"- {entry['source_id']} ok={str(entry['ok']).lower()} "
                f"status={entry['status']} skipped={str(entry['skipped']).lower()}"
            )
    return 0 if payload["failed_count"] == 0 else 1


def _sources_validate(args: argparse.Namespace) -> int:
    result = SourceApplicationService().validate_sources()
    payload = result.to_dict()

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"is_valid={str(payload['is_valid']).lower()}")
        print(f"error_count={payload['error_count']}")
        print(f"warning_count={payload['warning_count']}")
        for issue in payload["issues"]:
            print(
                f"- {issue['severity']} {issue['source_id']}.{issue['field']}: "
                f"{issue['message']}"
            )
    return 0 if payload["is_valid"] else 2


def _runs_list(args: argparse.Namespace) -> int:
    result = RunInspectionService(artifact_root=args.artifact_root).list_runs(limit=args.limit)
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"run_count={payload['run_count']}")
        for run in payload["runs"]:
            print(f"- {run['run_id']} status={run['status']} profile={run['profile']}")
            print(f"  started_at={run['started_at']} manifest={run['manifest_path']}")
    return 0


def _runs_show(args: argparse.Namespace) -> int:
    try:
        result = RunInspectionService(artifact_root=args.artifact_root).get_run(args.run_id)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        manifest = payload["manifest"]
        print(f"run_id={payload['run_id']}")
        print(f"status={manifest.get('status')}")
        print(f"workflow_id={manifest.get('workflow_id')}")
        print(f"profile={manifest.get('profile')}")
        print(f"manifest_path={payload['manifest_path']}")
    return 0


def _runs_events(args: argparse.Namespace) -> int:
    try:
        result = RunInspectionService(artifact_root=args.artifact_root).get_run_events(
            args.run_id,
            limit=args.limit,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"run_id={payload['run_id']}")
        print(f"event_count={payload['event_count']}")
        for event in payload["events"]:
            print(f"- {event.get('event_type')} at {event.get('occurred_at')}")
    return 0


def _runs_replay(args: argparse.Namespace) -> int:
    try:
        result = RunInspectionService(artifact_root=args.artifact_root).replay_run(args.run_id)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        manifest = payload["manifest"]
        print(f"run_id={payload['run_id']}")
        print(f"status={manifest.get('status')}")
        print(f"manifest_path={payload['manifest_path']}")
        print(f"event_count={payload['event_count']}")
        if payload["events_error"]:
            print(f"events_error={payload['events_error']}")
        print(f"artifact_count={payload['artifact_count']}")
        for artifact in payload["artifacts"]:
            line = (
                f"- {artifact['artifact_key']} path={artifact['relative_path']} "
                f"type={artifact['content_type']} size={artifact['size_bytes']}"
            )
            if artifact["read_error"]:
                line = f"{line} error={artifact['read_error']}"
            print(line)
    return 0


def _artifacts_list(args: argparse.Namespace) -> int:
    try:
        result = ArtifactInspectionService(artifact_root=args.artifact_root).list_artifacts(args.run_id)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"run_id={payload['run_id']}")
        print(f"artifact_count={payload['artifact_count']}")
        for artifact in payload["artifacts"]:
            print(
                f"- {artifact['artifact_key']} path={artifact['relative_path']} "
                f"type={artifact['content_type']} size={artifact['size_bytes']}"
            )
    return 0


def _artifacts_show(args: argparse.Namespace) -> int:
    try:
        result = ArtifactInspectionService(artifact_root=args.artifact_root).get_artifact(
            args.run_id,
            args.artifact_key,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc))
        return 1
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    elif isinstance(payload["content"], str):
        print(payload["content"])
    else:
        print(json.dumps(payload["content"], ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _add_tool_policy_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--allowed",
        dest="allowed_tools",
        action="append",
        default=None,
        help="Allowed tool name; can be passed multiple times",
    )
    parser.add_argument(
        "--blocked",
        dest="blocked_tools",
        action="append",
        default=None,
        help="Blocked tool name; can be passed multiple times",
    )
    parser.add_argument(
        "--allow-mcp",
        action="store_true",
        help="Expose MCP tools if present in the registry",
    )
    parser.add_argument(
        "--include-dangerous",
        action="store_true",
        help="Expose dangerous tools if present in the registry",
    )


def _tools_list(args: argparse.Namespace) -> int:
    registry = build_builtin_tool_registry()
    catalog = build_tool_catalog(
        registry,
        agent_id="cli",
        policy=_tool_policy_from_args(args),
    )
    payload = catalog.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"tool_count={payload['tool_count']}")
        print(f"namespace_count={payload['namespace_count']}")
        for namespace in payload["namespaces"]:
            print(f"- {namespace['namespace']} tools={namespace['tool_count']}")
        for tool in payload["tools"]:
            print(f"{tool['name']}@{tool['version']} side_effect={tool['side_effect']}")
    return 0 if catalog.registry_valid else 1


def _tools_schema(args: argparse.Namespace) -> int:
    registry = build_builtin_tool_registry()
    policy = _tool_policy_from_args(args)
    tools = registry.export_schema_for_llm(args.agent_id, policy)
    payload = {
        "agent_id": args.agent_id,
        "tool_count": len(tools),
        "tools": tools,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"agent_id={payload['agent_id']}")
        print(f"tool_count={payload['tool_count']}")
        for tool in payload["tools"]:
            print(f"- {tool['name']}@{tool['version']}")
    return 0


def _tool_policy_from_args(args: argparse.Namespace) -> ToolPolicy:
    allowed_tools = list(args.allowed_tools or [])
    return ToolPolicy(
        allowed_tools=allowed_tools,
        blocked_tools=list(args.blocked_tools or []),
        allow_mcp_tools=bool(args.allow_mcp),
        allow_dangerous_tools=bool(args.include_dangerous),
        require_explicit_allowlist=bool(allowed_tools),
    )


def _mcp_catalog(args: argparse.Namespace) -> int:
    catalog = MCPApplicationService().catalog().to_dict()
    if args.json:
        print(json.dumps(catalog, ensure_ascii=False, sort_keys=True))
    else:
        print(f"tools={len(catalog['tools'])}")
        for tool in catalog["tools"]:
            print(f"- {tool['name']}: {tool['description']}")
        print(f"resources={len(catalog['resources'])}")
        for resource in catalog["resources"]:
            print(f"- {resource['uri']}: {resource['description']}")
        print(f"prompts={len(catalog['prompts'])}")
        for prompt in catalog["prompts"]:
            print(f"- {prompt['name']}: {prompt['description']}")
    return 0


def _mcp_call(args: argparse.Namespace) -> int:
    arguments = _parse_json_object(args.args_json)
    result = MCPApplicationService().call_tool(args.tool_name, arguments)
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"tool_name={payload['tool_name']}")
        print(f"success={str(payload['success']).lower()}")
        if payload["error_message"]:
            print(f"error={payload['error_message']}")
        elif payload["data"] is not None:
            print(json.dumps(payload["data"], ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.success else 1


def _mcp_read_resource(args: argparse.Namespace) -> int:
    result = MCPApplicationService().read_resource(args.uri)
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"uri={payload['uri']}")
        print(f"success={str(payload['success']).lower()}")
        if payload["error_message"]:
            print(f"error={payload['error_message']}")
        elif payload["data"] is not None:
            print(json.dumps(payload["data"], ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.success else 1


def _mcp_get_prompt(args: argparse.Namespace) -> int:
    arguments = _parse_json_object(args.args_json)
    result = MCPApplicationService().get_prompt(args.prompt_name, arguments)
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"name={payload['name']}")
        print(f"success={str(payload['success']).lower()}")
        if payload["error_message"]:
            print(f"error={payload['error_message']}")
        else:
            for message in payload["messages"]:
                print(f"[{message['role']}] {message['content']}")
    return 0 if result.success else 1


def _parse_json_object(value: str) -> dict:
    payload = json.loads(value)
    if not isinstance(payload, dict):
        raise SystemExit("--args-json must be a JSON object")
    return payload


def _parse_cli_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError as exc:
        raise SystemExit(f"invalid ISO datetime: {value}") from exc


def _mcp_serve_stdio(args: argparse.Namespace) -> int:
    from interfaces.mcp.stdio_server import run_stdio

    run_stdio()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
