from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Callable
from urllib.parse import unquote

from interfaces.mcp.models import (
    MCPCatalog,
    MCPPrompt,
    MCPPromptGetResult,
    MCPResource,
    MCPResourceReadResult,
    MCPTool,
    MCPToolCallResult,
)


DEFAULT_DAILY_QUEUE = "news:queue:daily"
DEFAULT_MEMORY_COLLECTION = "report_sections"
LATEST_REPORT_RESOURCE_URI = "news://reports/latest"
REPORT_RESOURCE_TEMPLATE = "news://reports/{report_id}"
REPORT_RESOURCE_PREFIX = "news://reports/"
RUN_MANIFEST_RESOURCE_TEMPLATE = "news://runs/{run_id}/manifest"
RUN_MANIFEST_RESOURCE_PREFIX = "news://runs/"
RUN_MANIFEST_RESOURCE_SUFFIX = "/manifest"
RUN_EVENTS_RESOURCE_TEMPLATE = "news://runs/{run_id}/events"
RUN_EVENTS_RESOURCE_SUFFIX = "/events"
RUN_REPLAY_RESOURCE_TEMPLATE = "news://runs/{run_id}/replay"
RUN_REPLAY_RESOURCE_SUFFIX = "/replay"
RUN_LINEAGE_RESOURCE_TEMPLATE = "news://runs/{run_id}/lineage"
RUN_LINEAGE_RESOURCE_SUFFIX = "/lineage"
RUN_LINEAGE_UPSTREAM_RESOURCE_TEMPLATE = "news://runs/{run_id}/lineage/upstream/{target_type}/{target_id}"
RUN_LINEAGE_UPSTREAM_RESOURCE_MARKER = "/lineage/upstream/"
RUN_LINEAGE_DOWNSTREAM_RESOURCE_TEMPLATE = (
    "news://runs/{run_id}/lineage/downstream/{source_type}/{source_id}"
)
RUN_LINEAGE_DOWNSTREAM_RESOURCE_MARKER = "/lineage/downstream/"
RUN_ARTIFACT_RESOURCE_TEMPLATE = "news://runs/{run_id}/artifacts/{artifact_key}"
RUN_ARTIFACT_RESOURCE_SEPARATOR = "/artifacts/"
STORAGE_METRICS_RESOURCE_URI = "news://storage/metrics"
SOURCE_HEALTH_RESOURCE_URI = "news://sources/health"


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
        run_inspection_service_factory: Callable[[], Any] | None = None,
        artifact_service_factory: Callable[[], Any] | None = None,
        storage_service_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.worker_service_factory = worker_service_factory or _worker_service_factory
        self.report_service_factory = report_service_factory or _report_service_factory
        self.source_service_factory = source_service_factory or _source_service_factory
        self.memory_service_factory = memory_service_factory or _memory_service_factory
        self.diagnostic_service_factory = diagnostic_service_factory or _diagnostic_service_factory
        self.approval_service_factory = approval_service_factory or _approval_service_factory
        self.run_inspection_service_factory = (
            run_inspection_service_factory or _run_inspection_service_factory
        )
        self.artifact_service_factory = artifact_service_factory or _artifact_service_factory
        self.storage_service_factory = storage_service_factory or _storage_service_factory

    def catalog(self) -> MCPCatalog:
        return MCPCatalog(tools=_tools(), resources=_resources(), prompts=_prompts())

    def get_prompt(self, name: str, arguments: dict[str, Any] | None = None) -> MCPPromptGetResult:
        args = arguments or {}
        try:
            template = _prompt_templates().get(name)
            if template is None:
                return MCPPromptGetResult(
                    name=name,
                    success=False,
                    error_type="MCPPromptNotFound",
                    error_message=f"unknown MCP prompt: {name}",
                )
            return MCPPromptGetResult(
                name=name,
                success=True,
                description=template["description"],
                messages=[
                    {
                        "role": "user",
                        "content": _render_prompt_text(str(template["text"]), args),
                    }
                ],
            )
        except Exception as exc:
            return MCPPromptGetResult(
                name=name,
                success=False,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

    def read_resource(self, uri: str) -> MCPResourceReadResult:
        try:
            if uri == LATEST_REPORT_RESOURCE_URI:
                return self._read_latest_report_resource()
            report_id = _report_resource_report_id(uri)
            if report_id is not None:
                return self._read_report_resource(uri, report_id)
            artifact_resource = _run_artifact_resource_ids(uri)
            if artifact_resource is not None:
                run_id, artifact_key = artifact_resource
                return self._read_run_artifact_resource(uri, run_id, artifact_key)
            run_id = _run_manifest_resource_run_id(uri)
            if run_id is not None:
                return self._read_run_manifest_resource(uri, run_id)
            run_id = _run_events_resource_run_id(uri)
            if run_id is not None:
                return self._read_run_events_resource(uri, run_id)
            run_id = _run_replay_resource_run_id(uri)
            if run_id is not None:
                return self._read_run_replay_resource(uri, run_id)
            lineage_upstream = _run_lineage_upstream_resource_ids(uri)
            if lineage_upstream is not None:
                run_id, target_type, target_id = lineage_upstream
                return self._read_run_lineage_upstream_resource(uri, run_id, target_type, target_id)
            lineage_downstream = _run_lineage_downstream_resource_ids(uri)
            if lineage_downstream is not None:
                run_id, source_type, source_id = lineage_downstream
                return self._read_run_lineage_downstream_resource(
                    uri,
                    run_id,
                    source_type,
                    source_id,
                )
            run_id = _run_lineage_resource_run_id(uri)
            if run_id is not None:
                return self._read_run_lineage_resource(uri, run_id)
            if uri == STORAGE_METRICS_RESOURCE_URI:
                return self._read_storage_metrics_resource()
            if uri == SOURCE_HEALTH_RESOURCE_URI:
                return self._read_source_health_resource()
            return MCPResourceReadResult(
                uri=uri,
                success=False,
                error_type="MCPResourceNotFound",
                error_message=f"unknown MCP resource: {uri}",
            )
        except Exception as exc:
            return MCPResourceReadResult(
                uri=uri,
                success=False,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

    def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> MCPToolCallResult:
        args = arguments or {}
        try:
            if tool_name == "news.daily.enqueue":
                return self._daily_enqueue(args)
            if tool_name == "news.report.latest":
                return self._latest_report()
            if tool_name == "news.report.search":
                return self._report_search(args)
            if tool_name == "news.source.health":
                return self._source_health(args)
            if tool_name == "news.memory.search":
                return self._memory_search(args)
            if tool_name == "news.diagnose":
                return self._diagnose()
            if tool_name == "news.run.show":
                return self._run_show(args)
            if tool_name == "news.run.events":
                return self._run_events(args)
            if tool_name == "news.run.replay":
                return self._run_replay(args)
            if tool_name == "news.run.lineage":
                return self._run_lineage(args)
            if tool_name == "news.run.lineage.upstream":
                return self._run_lineage_upstream(args)
            if tool_name == "news.run.lineage.downstream":
                return self._run_lineage_downstream(args)
            if tool_name == "news.storage.metrics":
                return self._storage_metrics()
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

    def _report_search(self, args: dict[str, Any]) -> MCPToolCallResult:
        query = str(args.get("query") or "")
        result = self.report_service_factory().search_reports(
            query=query,
            limit=int(args.get("limit") or 20),
        )
        return MCPToolCallResult(
            tool_name="news.report.search",
            success=True,
            data=result.to_dict(),
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

    def _run_show(self, args: dict[str, Any]) -> MCPToolCallResult:
        run_id = str(args.get("run_id") or "")
        if not run_id:
            raise ValueError("run_id is required")
        result = self.run_inspection_service_factory().get_run(run_id)
        return MCPToolCallResult(
            tool_name="news.run.show",
            success=True,
            data=result.to_dict(),
        )

    def _run_events(self, args: dict[str, Any]) -> MCPToolCallResult:
        run_id = str(args.get("run_id") or "")
        if not run_id:
            raise ValueError("run_id is required")
        result = self.run_inspection_service_factory().get_run_events(
            run_id,
            limit=int(args["limit"]) if args.get("limit") is not None else None,
        )
        return MCPToolCallResult(
            tool_name="news.run.events",
            success=True,
            data=result.to_dict(),
        )

    def _run_replay(self, args: dict[str, Any]) -> MCPToolCallResult:
        run_id = str(args.get("run_id") or "")
        if not run_id:
            raise ValueError("run_id is required")
        result = self.run_inspection_service_factory().replay_run(run_id)
        return MCPToolCallResult(
            tool_name="news.run.replay",
            success=True,
            data=result.to_dict(),
        )

    def _run_lineage(self, args: dict[str, Any]) -> MCPToolCallResult:
        run_id = _required_arg(args, "run_id")
        result = self.storage_service_factory().list_lineage(run_id)
        return MCPToolCallResult(
            tool_name="news.run.lineage",
            success=True,
            data=result.to_dict(),
        )

    def _run_lineage_upstream(self, args: dict[str, Any]) -> MCPToolCallResult:
        result = self.storage_service_factory().lineage_upstream(
            run_id=_required_arg(args, "run_id"),
            target_type=_required_arg(args, "target_type"),
            target_id=_required_arg(args, "target_id"),
        )
        return MCPToolCallResult(
            tool_name="news.run.lineage.upstream",
            success=True,
            data=result.to_dict(),
        )

    def _run_lineage_downstream(self, args: dict[str, Any]) -> MCPToolCallResult:
        result = self.storage_service_factory().lineage_downstream(
            run_id=_required_arg(args, "run_id"),
            source_type=_required_arg(args, "source_type"),
            source_id=_required_arg(args, "source_id"),
        )
        return MCPToolCallResult(
            tool_name="news.run.lineage.downstream",
            success=True,
            data=result.to_dict(),
        )

    def _storage_metrics(self) -> MCPToolCallResult:
        result = self.storage_service_factory().metrics()
        return MCPToolCallResult(
            tool_name="news.storage.metrics",
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

    def _read_latest_report_resource(self) -> MCPResourceReadResult:
        record = self.report_service_factory().latest_report()
        return MCPResourceReadResult(
            uri=LATEST_REPORT_RESOURCE_URI,
            success=True,
            data=_to_dict(record),
        )

    def _read_report_resource(self, uri: str, report_id: str) -> MCPResourceReadResult:
        record = self.report_service_factory().get_report(report_id)
        return MCPResourceReadResult(
            uri=uri,
            success=True,
            data=_to_dict(record),
        )

    def _read_run_manifest_resource(self, uri: str, run_id: str) -> MCPResourceReadResult:
        result = self.run_inspection_service_factory().get_run(run_id)
        return MCPResourceReadResult(
            uri=uri,
            success=True,
            data=result.to_dict(),
        )

    def _read_run_events_resource(self, uri: str, run_id: str) -> MCPResourceReadResult:
        result = self.run_inspection_service_factory().get_run_events(run_id)
        return MCPResourceReadResult(
            uri=uri,
            success=True,
            data=result.to_dict(),
        )

    def _read_run_replay_resource(self, uri: str, run_id: str) -> MCPResourceReadResult:
        result = self.run_inspection_service_factory().replay_run(run_id)
        return MCPResourceReadResult(
            uri=uri,
            success=True,
            data=result.to_dict(),
        )

    def _read_run_lineage_resource(self, uri: str, run_id: str) -> MCPResourceReadResult:
        result = self.storage_service_factory().list_lineage(run_id)
        return MCPResourceReadResult(
            uri=uri,
            success=True,
            data=result.to_dict(),
        )

    def _read_run_lineage_upstream_resource(
        self,
        uri: str,
        run_id: str,
        target_type: str,
        target_id: str,
    ) -> MCPResourceReadResult:
        result = self.storage_service_factory().lineage_upstream(
            run_id=run_id,
            target_type=target_type,
            target_id=target_id,
        )
        return MCPResourceReadResult(
            uri=uri,
            success=True,
            data=result.to_dict(),
        )

    def _read_run_lineage_downstream_resource(
        self,
        uri: str,
        run_id: str,
        source_type: str,
        source_id: str,
    ) -> MCPResourceReadResult:
        result = self.storage_service_factory().lineage_downstream(
            run_id=run_id,
            source_type=source_type,
            source_id=source_id,
        )
        return MCPResourceReadResult(
            uri=uri,
            success=True,
            data=result.to_dict(),
        )

    def _read_storage_metrics_resource(self) -> MCPResourceReadResult:
        result = self.storage_service_factory().metrics()
        return MCPResourceReadResult(
            uri=STORAGE_METRICS_RESOURCE_URI,
            success=True,
            data=result.to_dict(),
        )

    def _read_run_artifact_resource(
        self,
        uri: str,
        run_id: str,
        artifact_key: str,
    ) -> MCPResourceReadResult:
        result = self.artifact_service_factory().get_artifact(run_id, artifact_key)
        return MCPResourceReadResult(
            uri=uri,
            success=True,
            data=result.to_dict(),
        )

    def _read_source_health_resource(self) -> MCPResourceReadResult:
        result = self.source_service_factory().source_health(enabled_only=True)
        return MCPResourceReadResult(
            uri=SOURCE_HEALTH_RESOURCE_URI,
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
            name="news.report.search",
            title="Search reports",
            description="Search persisted report artifacts through ReportApplicationService.",
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1},
                },
            },
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
            name="news.run.show",
            title="Show run",
            description="Read one workflow run manifest through RunInspectionService.",
            input_schema={
                "type": "object",
                "required": ["run_id"],
                "properties": {"run_id": {"type": "string"}},
            },
        ),
        MCPTool(
            name="news.run.events",
            title="Show run events",
            description="Read structured workflow run events through RunInspectionService.",
            input_schema={
                "type": "object",
                "required": ["run_id"],
                "properties": {
                    "run_id": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1},
                },
            },
        ),
        MCPTool(
            name="news.run.replay",
            title="Replay run artifacts",
            description="Read a redacted run replay bundle through RunInspectionService.",
            input_schema={
                "type": "object",
                "required": ["run_id"],
                "properties": {"run_id": {"type": "string"}},
            },
        ),
        MCPTool(
            name="news.run.lineage",
            title="List run lineage",
            description="Read local lineage refs for a run through StorageApplicationService.",
            input_schema={
                "type": "object",
                "required": ["run_id"],
                "properties": {"run_id": {"type": "string"}},
            },
        ),
        MCPTool(
            name="news.run.lineage.upstream",
            title="Read upstream run lineage",
            description="Read upstream lineage refs for a target through StorageApplicationService.",
            input_schema={
                "type": "object",
                "required": ["run_id", "target_type", "target_id"],
                "properties": {
                    "run_id": {"type": "string"},
                    "target_type": {"type": "string"},
                    "target_id": {"type": "string"},
                },
            },
        ),
        MCPTool(
            name="news.run.lineage.downstream",
            title="Read downstream run lineage",
            description="Read downstream lineage refs for a source through StorageApplicationService.",
            input_schema={
                "type": "object",
                "required": ["run_id", "source_type", "source_id"],
                "properties": {
                    "run_id": {"type": "string"},
                    "source_type": {"type": "string"},
                    "source_id": {"type": "string"},
                },
            },
        ),
        MCPTool(
            name="news.storage.metrics",
            title="Read storage metrics",
            description="Read local storage metrics through StorageApplicationService.",
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
            uri=LATEST_REPORT_RESOURCE_URI,
            name="Latest Report",
            description="Latest redacted report view.",
        ),
        MCPResource(
            uri=REPORT_RESOURCE_TEMPLATE,
            name="Report Detail",
            description="Persisted report detail by report id.",
        ),
        MCPResource(
            uri=RUN_MANIFEST_RESOURCE_TEMPLATE,
            name="Run Manifest",
            description="Workflow run manifest by run id.",
        ),
        MCPResource(
            uri=RUN_EVENTS_RESOURCE_TEMPLATE,
            name="Run Events",
            description="Structured workflow run events by run id.",
        ),
        MCPResource(
            uri=RUN_REPLAY_RESOURCE_TEMPLATE,
            name="Run Replay",
            description="Redacted workflow run replay bundle by run id.",
        ),
        MCPResource(
            uri=RUN_LINEAGE_RESOURCE_TEMPLATE,
            name="Run Lineage",
            description="Local lineage refs by run id.",
        ),
        MCPResource(
            uri=RUN_LINEAGE_UPSTREAM_RESOURCE_TEMPLATE,
            name="Run Upstream Lineage",
            description="Upstream lineage refs for a target by run id.",
        ),
        MCPResource(
            uri=RUN_LINEAGE_DOWNSTREAM_RESOURCE_TEMPLATE,
            name="Run Downstream Lineage",
            description="Downstream lineage refs for a source by run id.",
        ),
        MCPResource(
            uri=RUN_ARTIFACT_RESOURCE_TEMPLATE,
            name="Run Artifact",
            description="Manifest-listed workflow artifact by run id and artifact key.",
        ),
        MCPResource(
            uri=STORAGE_METRICS_RESOURCE_URI,
            name="Storage Metrics",
            description="Local storage metrics.",
        ),
        MCPResource(
            uri=SOURCE_HEALTH_RESOURCE_URI,
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
        MCPPrompt(
            name="news.quality_gate_explain",
            description="Explain quality gate decisions and remediation options.",
            arguments_schema={
                "type": "object",
                "properties": {
                    "run_id": {"type": "string"},
                    "quality_gate_id": {"type": "string"},
                },
            },
        ),
        MCPPrompt(
            name="news.trend_analysis_prompt",
            description="Analyze trends across report or memory search context.",
            arguments_schema={
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "time_window": {"type": "string"},
                },
            },
        ),
    ]


def _prompt_templates() -> dict[str, dict[str, str]]:
    return {
        "news.daily_report_review": {
            "description": "Review a generated daily report for evidence coverage and clarity.",
            "text": (
                "Review the daily intelligence report.\n"
                "Report id: {report_id}\n"
                "Check evidence coverage, citation clarity, unsupported claims, and rewrite risks. "
                "Return concise findings and recommended fixes."
            ),
        },
        "news.evidence_audit": {
            "description": "Audit evidence lineage and citation support.",
            "text": (
                "Audit evidence lineage for run {run_id}.\n"
                "Verify that report sections are supported by evidence items and cited source URLs. "
                "Flag missing, weak, or stale evidence."
            ),
        },
        "news.source_diagnose": {
            "description": "Diagnose source health and reliability issues.",
            "text": (
                "Diagnose source health for source {source_id}.\n"
                "Review recent failures, cooldown state, reliability, and remediation steps."
            ),
        },
        "news.quality_gate_explain": {
            "description": "Explain quality gate decisions and remediation options.",
            "text": (
                "Explain the quality gate result for run {run_id}.\n"
                "Quality gate id: {quality_gate_id}\n"
                "Summarize the decision, failed checks, and concrete remediation steps."
            ),
        },
        "news.trend_analysis_prompt": {
            "description": "Analyze trends across report or memory search context.",
            "text": (
                "Analyze trends for topic {topic} over {time_window}.\n"
                "Compare recurring entities, policy shifts, evidence changes, and confidence limits. "
                "Separate historical context from current facts."
            ),
        },
    }


def _render_prompt_text(template: str, arguments: dict[str, Any]) -> str:
    values = {key: str(value) for key, value in arguments.items()}
    for key in _prompt_placeholder_names(template):
        values.setdefault(key, "<unspecified>")
    return template.format(**values)


def _prompt_placeholder_names(template: str) -> set[str]:
    import string

    return {
        field_name
        for _, field_name, _, _ in string.Formatter().parse(template)
        if field_name
    }


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


def _run_inspection_service_factory():
    from interfaces.services.run_inspection_service import RunInspectionService

    return RunInspectionService()


def _artifact_service_factory():
    from interfaces.services.artifact_service import ArtifactInspectionService

    return ArtifactInspectionService()


def _storage_service_factory():
    from interfaces.services.storage_service import StorageApplicationService

    return StorageApplicationService()


def _report_resource_report_id(uri: str) -> str | None:
    if not uri.startswith(REPORT_RESOURCE_PREFIX):
        return None
    report_id = uri[len(REPORT_RESOURCE_PREFIX) :]
    return report_id or None


def _run_manifest_resource_run_id(uri: str) -> str | None:
    if not uri.startswith(RUN_MANIFEST_RESOURCE_PREFIX) or not uri.endswith(
        RUN_MANIFEST_RESOURCE_SUFFIX
    ):
        return None
    run_id = uri[len(RUN_MANIFEST_RESOURCE_PREFIX) : -len(RUN_MANIFEST_RESOURCE_SUFFIX)]
    return run_id or None


def _run_events_resource_run_id(uri: str) -> str | None:
    if not uri.startswith(RUN_MANIFEST_RESOURCE_PREFIX) or not uri.endswith(
        RUN_EVENTS_RESOURCE_SUFFIX
    ):
        return None
    run_id = uri[len(RUN_MANIFEST_RESOURCE_PREFIX) : -len(RUN_EVENTS_RESOURCE_SUFFIX)]
    return run_id or None


def _run_replay_resource_run_id(uri: str) -> str | None:
    if not uri.startswith(RUN_MANIFEST_RESOURCE_PREFIX) or not uri.endswith(
        RUN_REPLAY_RESOURCE_SUFFIX
    ):
        return None
    run_id = uri[len(RUN_MANIFEST_RESOURCE_PREFIX) : -len(RUN_REPLAY_RESOURCE_SUFFIX)]
    return run_id or None


def _run_lineage_resource_run_id(uri: str) -> str | None:
    if not uri.startswith(RUN_MANIFEST_RESOURCE_PREFIX) or not uri.endswith(
        RUN_LINEAGE_RESOURCE_SUFFIX
    ):
        return None
    run_id = uri[len(RUN_MANIFEST_RESOURCE_PREFIX) : -len(RUN_LINEAGE_RESOURCE_SUFFIX)]
    return run_id or None


def _run_lineage_upstream_resource_ids(uri: str) -> tuple[str, str, str] | None:
    return _run_lineage_resource_ids(uri, RUN_LINEAGE_UPSTREAM_RESOURCE_MARKER)


def _run_lineage_downstream_resource_ids(uri: str) -> tuple[str, str, str] | None:
    return _run_lineage_resource_ids(uri, RUN_LINEAGE_DOWNSTREAM_RESOURCE_MARKER)


def _run_lineage_resource_ids(uri: str, marker: str) -> tuple[str, str, str] | None:
    if not uri.startswith(RUN_MANIFEST_RESOURCE_PREFIX):
        return None
    rest = uri[len(RUN_MANIFEST_RESOURCE_PREFIX) :]
    if marker not in rest:
        return None
    run_id, resource_ids = rest.split(marker, 1)
    parts = resource_ids.split("/", 1)
    if not run_id or len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return unquote(run_id), unquote(parts[0]), unquote(parts[1])


def _run_artifact_resource_ids(uri: str) -> tuple[str, str] | None:
    if not uri.startswith(RUN_MANIFEST_RESOURCE_PREFIX):
        return None
    rest = uri[len(RUN_MANIFEST_RESOURCE_PREFIX) :]
    if RUN_ARTIFACT_RESOURCE_SEPARATOR not in rest:
        return None
    run_id, artifact_key = rest.split(RUN_ARTIFACT_RESOURCE_SEPARATOR, 1)
    if not run_id or not artifact_key:
        return None
    return run_id, artifact_key


def _approval_id(args: dict[str, Any]) -> str:
    approval_id = str(args.get("approval_id") or "")
    if not approval_id:
        raise ValueError("approval_id is required")
    return approval_id


def _required_arg(args: dict[str, Any], name: str) -> str:
    value = str(args.get(name) or "")
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _decided_by(args: dict[str, Any]) -> str:
    decided_by = str(args.get("decided_by") or "")
    if not decided_by:
        raise ValueError("decided_by is required")
    return decided_by
