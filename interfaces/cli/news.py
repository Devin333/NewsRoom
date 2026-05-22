from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

from business.boards.cross_board.profiles import DAILY_PROFILE_CHOICES
from business.tools import build_business_tool_registry
from framework.specs import WorkflowStatus
from framework.tool import ToolPolicy, build_tool_catalog
from framework.workers import WorkerStatus
from framework.workers.approval import ApprovalAlreadyDecidedError, ApprovalNotFoundError
from framework.workers.scheduler import ScheduleRecord, ScheduleSpec
from interfaces.cli.commands import (
    api,
    approvals,
    artifacts,
    dev,
    diagnose,
    entities,
    mcp,
    memory,
    reports,
    run,
    runs,
    schedules,
    sources,
    storage,
    subscriptions,
    tools,
    workers,
)
from interfaces.cli.commands import reports as reports_commands
from interfaces.cli.commands import subscriptions as subscription_commands
from interfaces.services.approval_service import (
    DEFAULT_APPROVAL_STORE_PATH,
    ApprovalApplicationService,
)
from interfaces.services.artifact_service import ArtifactInspectionService
from interfaces.services.diagnose_service import DiagnosticApplicationService
from interfaces.services.entity_service import (
    DEFAULT_ENTITY_STORE_PATH,
    EntityTrackingApplicationService,
)
from interfaces.services.mcp_service import MCPApplicationService
from interfaces.services.memory_service import DEFAULT_MEMORY_COLLECTION, MemoryApplicationService
from interfaces.services.report_service import ReportApplicationService
from interfaces.services.run_inspection_service import RunInspectionService
from interfaces.services.run_operation_service import RunOperationApplicationService
from interfaces.services.run_service import DEFAULT_CHECKPOINT_STORE_PATH, RunApplicationService
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
from infrastructure.storage.lifecycle import RetentionPolicy


COMMAND_MODULES = (
    run,
    reports,
    subscriptions,
    entities,
    api,
    workers,
    schedules,
    approvals,
    memory,
    diagnose,
    storage,
    sources,
    runs,
    artifacts,
    tools,
    mcp,
    dev,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="news", description="NewsRoom command line interface")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command_module in COMMAND_MODULES:
        command_module.register(subparsers)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


def print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


__all__ = [
    "Any",
    "ApprovalAlreadyDecidedError",
    "ApprovalApplicationService",
    "ApprovalNotFoundError",
    "ArtifactInspectionService",
    "DAILY_PROFILE_CHOICES",
    "DEFAULT_APPROVAL_STORE_PATH",
    "DEFAULT_CHECKPOINT_STORE_PATH",
    "DEFAULT_DAILY_QUEUE",
    "DEFAULT_DEAD_LETTER_QUEUE",
    "DEFAULT_ENTITY_STORE_PATH",
    "DEFAULT_MEMORY_COLLECTION",
    "DEFAULT_MEMORY_QUEUE",
    "DEFAULT_SCHEDULE_STORE_PATH",
    "DEFAULT_SOURCE_QUEUE",
    "DEFAULT_SUBSCRIPTION_STORE_PATH",
    "DiagnosticApplicationService",
    "EntityTrackingApplicationService",
    "MCPApplicationService",
    "MemoryApplicationService",
    "Path",
    "ReportApplicationService",
    "RetentionPolicy",
    "RunApplicationService",
    "RunInspectionService",
    "RunOperationApplicationService",
    "ScheduleApplicationService",
    "ScheduleRecord",
    "ScheduleSpec",
    "Sequence",
    "SourceApplicationService",
    "StorageApplicationService",
    "SubscriptionApplicationService",
    "ToolPolicy",
    "UTC",
    "WorkerApplicationService",
    "WorkerStatus",
    "WorkflowStatus",
    "argparse",
    "build_parser",
    "build_business_tool_registry",
    "build_tool_catalog",
    "datetime",
    "json",
    "main",
    "print_json",
    "reports_commands",
    "subscription_commands",
]
