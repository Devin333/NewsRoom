from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Callable

from interfaces.mcp.models import MCPCatalog, MCPPrompt, MCPResource, MCPTool, MCPToolCallResult


DEFAULT_DAILY_QUEUE = "news:queue:daily"
DEFAULT_MEMORY_COLLECTION = "report_sections"


class MCPApplicationService:
    def __init__(
        self,
        *,
        worker_service_factory: Callable[[], Any] | None = None,
        report_service_factory: Callable[[], Any] | None = None,
        source_service_factory: Callable[[], Any] | None = None,
        memory_service_factory: Callable[[], Any] | None = None,
        diagnostic_service_factory: Callable[[], Any] | None = None,
        approval_service_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.worker_service_factory = worker_service_factory or _worker_service_factory
        self.report_service_factory = report_service_factory or _report_service_factory
        self.source_service_factory = source_service_factory or _source_service_factory
        self.memory_service_factory = memory_service_factory or _memory_service_factory
        self.diagnostic_service_factory = diagnostic_service_factory or _diagnostic_service_factory
        self.approval_service_factory = approval_service_factory or _approval_service_factory

    def catalog(self) -> MCPCatalog:
        return MCPCatalog(tools=_tools(), resources=_resources(), prompts=_prompts())

    def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> MCPToolCallResult:
        args = arguments or {}
        try:
            if tool_name == "news.daily.enqueue":
                return self._daily_enqueue(args)
            if tool_name == "news.report.latest":
                return self._latest_report()
            if tool_name == "news.source.health":
                return self._source_health(args)
            if tool_name == "news.memory.search":
                return self._memory_search(args)
            if tool_name == "news.diagnose":
                return self._diagnose()
            if tool_name == "news.approval.submit":
                return self._approval_submit(args)
            if tool_name == "news.approval.list":
                return self._approval_list(args)
            if tool_name == "news.approval.get":
                return self._approval_get(args)
            if tool_name == "news.approval.approve":
                return self._approval_approve(args)
            if tool_name == "news.approval.reject":
                return self._approval_reject(args)
            if tool_name == "news.approval.modify":
                return self._approval_modify(args)
            return MCPToolCallResult(
                tool_name=tool_name,
                success=False,
                error_type="MCPToolNotFound",
                error_message=f"unknown MCP tool: {tool_name}",
            )
        except Exception as exc:
            return MCPToolCallResult(
                tool_name=tool_name,
                success=False,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

    def _daily_enqueue(self, args: dict[str, Any]) -> MCPToolCallResult:
        result = self.worker_service_factory().enqueue_daily(
            profile=str(args.get("profile") or "live-offline"),
            topic=str(args.get("topic") or "AI"),
            source_limit=int(args.get("source_limit") or 3),
            run_id=args.get("run_id"),
            queue_name=str(args.get("queue_name") or DEFAULT_DAILY_QUEUE),
        )
        return MCPToolCallResult(
            tool_name="news.daily.enqueue",
            success=True,
            data=result.to_dict(),
        )

    def _latest_report(self) -> MCPToolCallResult:
        record = self.report_service_factory().latest_report()
        return MCPToolCallResult(
            tool_name="news.report.latest",
            success=True,
            data=_to_dict(record),
        )

    def _source_health(self, args: dict[str, Any]) -> MCPToolCallResult:
        include_disabled = bool(args.get("include_disabled", False))
        result = self.source_service_factory().source_health(enabled_only=not include_disabled)
        return MCPToolCallResult(
            tool_name="news.source.health",
            success=True,
            data=result.to_dict(),
        )

    def _memory_search(self, args: dict[str, Any]) -> MCPToolCallResult:
        query = str(args.get("query") or "")
        if not query:
            raise ValueError("query is required")
        result = self.memory_service_factory().search(
            text=query,
            collection=str(args.get("collection") or DEFAULT_MEMORY_COLLECTION),
            limit=int(args.get("limit") or 5),
            filters=dict(args.get("filters") or {}),
        )
        return MCPToolCallResult(
            tool_name="news.memory.search",
            success=True,
            data=result.to_dict(),
        )

    def _diagnose(self) -> MCPToolCallResult:
        result = self.diagnostic_service_factory().run()
        return MCPToolCallResult(
            tool_name="news.diagnose",
            success=True,
            data=result.to_dict(),
        )

    def _approval_submit(self, args: dict[str, Any]) -> MCPToolCallResult:
        requested_action = str(args.get("requested_action") or "")
        if not requested_action:
            raise ValueError("requested_action is required")
        result = self.approval_service_factory().submit_request(
            requested_action=requested_action,
            risk_level=str(args.get("risk_level") or "medium"),
            reason=args.get("reason"),
            payload=dict(args.get("payload") or {}),
            task_id=args.get("task_id"),
            run_id=args.get("run_id"),
            requested_by=args.get("requested_by"),
            metadata=dict(args.get("metadata") or {}),
        )
        return MCPToolCallResult(
            tool_name="news.approval.submit",
            success=True,
            data=result.to_dict(),
        )

    def _approval_list(self, args: dict[str, Any]) -> MCPToolCallResult:
        result = self.approval_service_factory().list_approvals(status=args.get("status"))
        return MCPToolCallResult(
            tool_name="news.approval.list",
            success=True,
            data=result.to_dict(),
        )

    def _approval_get(self, args: dict[str, Any]) -> MCPToolCallResult:
        approval_id = str(args.get("approval_id") or "")
        if not approval_id:
            raise ValueError("approval_id is required")
        result = self.approval_service_factory().get_approval(approval_id)
        return MCPToolCallResult(
            tool_name="news.approval.get",
            success=True,
            data=result.to_dict(),
        )

    def _approval_approve(self, args: dict[str, Any]) -> MCPToolCallResult:
        result = self.approval_service_factory().approve(
            _approval_id(args),
            decided_by=_decided_by(args),
            reason=args.get("reason"),
        )
        return MCPToolCallResult(
            tool_name="news.approval.approve",
            success=True,
            data=result.to_dict(),
        )

    def _approval_reject(self, args: dict[str, Any]) -> MCPToolCallResult:
        result = self.approval_service_factory().reject(
            _approval_id(args),
            decided_by=_decided_by(args),
            reason=args.get("reason"),
        )
        return MCPToolCallResult(
            tool_name="news.approval.reject",
            success=True,
            data=result.to_dict(),
        )

    def _approval_modify(self, args: dict[str, Any]) -> MCPToolCallResult:
        result = self.approval_service_factory().modify(
            _approval_id(args),
            decided_by=_decided_by(args),
            modifications=dict(args.get("modifications") or {}),
            reason=args.get("reason"),
        )
        return MCPToolCallResult(
            tool_name="news.approval.modify",
            success=True,
            data=result.to_dict(),
        )


def _tools() -> list[MCPTool]:
    return [
        MCPTool(
            name="news.daily.enqueue",
            title="Enqueue daily intelligence run",
            description="Queue a daily intelligence workflow task through WorkerApplicationService.",
            input_schema={
                "type": "object",
                "properties": {
                    "profile": {"type": "string", "enum": ["live", "live-offline"]},
                    "topic": {"type": "string"},
                    "source_limit": {"type": "integer", "minimum": 1},
                    "run_id": {"type": "string"},
                    "queue_name": {"type": "string"},
                },
            },
        ),
        MCPTool(
            name="news.report.latest",
            title="Read latest report",
            description="Return the latest redacted report through ReportApplicationService.",
            input_schema={"type": "object", "properties": {}},
        ),
        MCPTool(
            name="news.source.health",
            title="Read source health",
            description="Return source health through SourceApplicationService.",
            input_schema={
                "type": "object",
                "properties": {"include_disabled": {"type": "boolean"}},
            },
        ),
        MCPTool(
            name="news.memory.search",
            title="Search vector memory",
            description="Search vector memory through MemoryApplicationService.",
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "collection": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1},
                    "filters": {"type": "object"},
                },
            },
        ),
        MCPTool(
            name="news.diagnose",
            title="Run diagnostics",
            description="Run local dependency diagnostics through DiagnosticApplicationService.",
            input_schema={"type": "object", "properties": {}},
        ),
        MCPTool(
            name="news.approval.submit",
            title="Submit approval request",
            description="Submit a human approval request through ApprovalApplicationService.",
            input_schema={
                "type": "object",
                "required": ["requested_action"],
                "properties": {
                    "requested_action": {"type": "string"},
                    "risk_level": {"type": "string"},
                    "reason": {"type": "string"},
                    "payload": {"type": "object"},
                    "task_id": {"type": "string"},
                    "run_id": {"type": "string"},
                    "requested_by": {"type": "string"},
                    "metadata": {"type": "object"},
                },
            },
        ),
        MCPTool(
            name="news.approval.list",
            title="List approvals",
            description="List human approval requests.",
            input_schema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["pending", "approved", "rejected", "modified", "expired", "cancelled"],
                    }
                },
            },
        ),
        MCPTool(
            name="news.approval.get",
            title="Get approval",
            description="Read one human approval request.",
            input_schema={
                "type": "object",
                "required": ["approval_id"],
                "properties": {"approval_id": {"type": "string"}},
            },
        ),
        MCPTool(
            name="news.approval.approve",
            title="Approve request",
            description="Approve a pending human approval request.",
            input_schema={
                "type": "object",
                "required": ["approval_id", "decided_by"],
                "properties": {
                    "approval_id": {"type": "string"},
                    "decided_by": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
        ),
        MCPTool(
            name="news.approval.reject",
            title="Reject request",
            description="Reject a pending human approval request.",
            input_schema={
                "type": "object",
                "required": ["approval_id", "decided_by"],
                "properties": {
                    "approval_id": {"type": "string"},
                    "decided_by": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
        ),
        MCPTool(
            name="news.approval.modify",
            title="Modify request",
            description="Approve a pending human approval request with modifications.",
            input_schema={
                "type": "object",
                "required": ["approval_id", "decided_by", "modifications"],
                "properties": {
                    "approval_id": {"type": "string"},
                    "decided_by": {"type": "string"},
                    "modifications": {"type": "object"},
                    "reason": {"type": "string"},
                },
            },
        ),
    ]


def _resources() -> list[MCPResource]:
    return [
        MCPResource(
            uri="news://reports/latest",
            name="Latest Report",
            description="Latest redacted report view.",
        ),
        MCPResource(
            uri="news://sources/health",
            name="Source Health",
            description="Current source health view.",
        ),
    ]


def _prompts() -> list[MCPPrompt]:
    return [
        MCPPrompt(
            name="news.daily_report_review",
            description="Review a generated daily report for evidence coverage and clarity.",
            arguments_schema={"type": "object", "properties": {"report_id": {"type": "string"}}},
        ),
        MCPPrompt(
            name="news.evidence_audit",
            description="Audit evidence lineage and citation support.",
            arguments_schema={"type": "object", "properties": {"run_id": {"type": "string"}}},
        ),
        MCPPrompt(
            name="news.source_diagnose",
            description="Diagnose source health and reliability issues.",
            arguments_schema={"type": "object", "properties": {"source_id": {"type": "string"}}},
        ),
    ]


def _to_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return dict(value)
    raise TypeError(f"value is not JSON-safe: {type(value).__name__}")


def _worker_service_factory():
    from interfaces.services.worker_service import WorkerApplicationService

    return WorkerApplicationService()


def _report_service_factory():
    from interfaces.services.report_service import ReportApplicationService

    return ReportApplicationService()


def _source_service_factory():
    from interfaces.services.source_service import SourceApplicationService

    return SourceApplicationService()


def _memory_service_factory():
    from interfaces.services.memory_service import MemoryApplicationService

    return MemoryApplicationService()


def _diagnostic_service_factory():
    from interfaces.services.diagnose_service import DiagnosticApplicationService

    return DiagnosticApplicationService()


def _approval_service_factory():
    from interfaces.services.approval_service import ApprovalApplicationService

    return ApprovalApplicationService()


def _approval_id(args: dict[str, Any]) -> str:
    approval_id = str(args.get("approval_id") or "")
    if not approval_id:
        raise ValueError("approval_id is required")
    return approval_id


def _decided_by(args: dict[str, Any]) -> str:
    decided_by = str(args.get("decided_by") or "")
    if not decided_by:
        raise ValueError("decided_by is required")
    return decided_by
