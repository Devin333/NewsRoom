from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from typing import Sequence

from core.framework.specs import WorkflowStatus
from core.framework.workers.approval import ApprovalAlreadyDecidedError, ApprovalNotFoundError
from core.framework.workers.schedule_store import ScheduleRecord
from core.framework.workers.scheduler import ScheduleSpec
from interfaces.services.approval_service import (
    ApprovalApplicationService,
    DEFAULT_APPROVAL_STORE_PATH,
)
from interfaces.services.artifact_service import ArtifactInspectionService
from interfaces.services.diagnose_service import DiagnosticApplicationService
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
from interfaces.services.worker_service import DEFAULT_DAILY_QUEUE, DEFAULT_MEMORY_QUEUE, WorkerApplicationService


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
        "--artifact-root",
        default=".newsroom/runs",
        help="Directory where run artifacts are written",
    )
    run_once_parser.add_argument("--redis-url", default=None, help="Redis URL; defaults to NEWS_REDIS_URL")
    run_once_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    run_once_parser.set_defaults(handler=_worker_run_once)

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

    diagnose_parser = subparsers.add_parser("diagnose", help="Run local diagnostics")
    diagnose_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    diagnose_parser.set_defaults(handler=_diagnose)

    sources_parser = subparsers.add_parser("sources", help="Inspect source registry and health")
    sources_subparsers = sources_parser.add_subparsers(dest="sources_command", required=True)

    sources_list_parser = sources_subparsers.add_parser("list", help="List registered sources")
    sources_list_parser.add_argument("--include-disabled", action="store_true", help="Include disabled sources")
    sources_list_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    sources_list_parser.set_defaults(handler=_sources_list)

    sources_health_parser = sources_subparsers.add_parser("health", help="Show source health")
    sources_health_parser.add_argument("--include-disabled", action="store_true", help="Include disabled sources")
    sources_health_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    sources_health_parser.set_defaults(handler=_sources_health)

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


def _worker_run_once(args: argparse.Namespace) -> int:
    service = WorkerApplicationService(artifact_root=args.artifact_root, redis_url=args.redis_url)
    result = service.run_once(
        worker_id=args.worker_id,
        queue_names=args.queue_names or [DEFAULT_DAILY_QUEUE],
        block_ms=args.block_ms,
    )
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
            print(f"success={str(payload['success']).lower()}")
            print(f"workflow_run_id={payload['workflow_run_id']}")
            if payload["error_message"]:
                print(f"error={payload['error_message']}")
    return 0 if result.success is not False else 1


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
                f"failures={item['consecutive_failures']}"
            )
    return 0


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
