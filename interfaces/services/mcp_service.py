from __future__ import annotations

from copy import copy
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone as _tz
import os
from typing import Any, Callable, Literal, cast
from urllib.parse import parse_qs, unquote, urlsplit

from framework.events.errors import (
    EventContractError,
    EventRuntimeError,
    EventStoreUnavailableError,
)
from framework.shared.public_errors import PublicErrorProjection, project_public_error
from interfaces.models.actor import ActorContext
from interfaces.mcp.models import (
    MCPCatalog,
    MCPCapability,
    MCPCapabilityManifest,
    MCPPrompt,
    MCPPromptGetResult,
    MCPResource,
    MCPResourceReadResult,
    MCPTool,
    MCPToolCallResult,
)
from interfaces.services.research_service import (
    ResearchActorAuthorizationError,
    ResearchActorInput,
    ResearchAnalyzeInput,
    ResearchAskInput,
    ResearchServiceError,
    bind_research_actor_input,
)
from interfaces.services.event_delivery_operations_service import (
    EventOperationCapabilityUnavailableError,
    EventOperationNotFoundError,
)
from interfaces.services.event_reader_service import EventAuthorizationError
from infrastructure.storage.lifecycle import RetentionPolicy


UTC = _tz.utc


DEFAULT_MEMORY_COLLECTION = "report_sections"
MCP_CAPABILITY_MANIFEST_VERSION = "1.0"
LATEST_REPORT_RESOURCE_URI = "news://reports/latest"
REPORT_RESOURCE_TEMPLATE = "news://reports/{report_id}"
REPORT_RESOURCE_PREFIX = "news://reports/"
RUN_MANIFEST_RESOURCE_TEMPLATE = "news://runs/{run_id}/manifest"
RUN_MANIFEST_RESOURCE_PREFIX = "news://runs/"
RUN_MANIFEST_RESOURCE_SUFFIX = "/manifest"
RUN_EVENTS_RESOURCE_TEMPLATE = "news://runs/{run_id}/events"
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
ARTIFACT_RESOURCE_TEMPLATE = "news://artifacts/{artifact_id}"
ARTIFACT_RESOURCE_PREFIX = "news://artifacts/"
MEMORY_RESOURCE_TEMPLATE = "news://memory/{document_id}"
MEMORY_RESOURCE_PREFIX = "news://memory/"
STORAGE_METRICS_RESOURCE_URI = "news://storage/metrics"
STORAGE_RETENTION_PLAN_RESOURCE_URI = "news://storage/retention/plan"
SOURCE_HEALTH_RESOURCE_URI = "news://sources/health"
WORKERS_RESOURCE_TEMPLATE = "news://workers"
WORKER_RESOURCE_TEMPLATE = "news://workers/{worker_id}"
QUEUES_RESOURCE_URI = "news://queues"
EVENT_QUARANTINE_RESOURCE_URI = "news://events/quarantine"
EVENT_QUARANTINE_RESOURCE_TEMPLATE = "news://events/quarantine/{quarantine_id}"
EVENT_REPLAY_REPORTS_RESOURCE_URI = "news://events/replay-reports"
EVENT_REPLAY_REPORT_RESOURCE_TEMPLATE = "news://events/replay-reports/{replay_id}"
EVENT_DEAD_LETTERS_RESOURCE_URI = "news://events/dead-letters"
EVENT_DEAD_LETTER_RESOURCE_TEMPLATE = "news://events/dead-letters/{dead_letter_id}"
EVENT_CONSUMER_STATUS_RESOURCE_TEMPLATE = (
    "news://events/consumers/{subscription_id}/versions/{version}/status"
)
EVENT_PROJECTION_STATUS_RESOURCE_TEMPLATE = (
    "news://events/projections/runs/{run_id}/status"
)
DANGEROUS_MCP_TOOLS = frozenset(
    {
        "news.report.publish",
        "news.run.cancel",
        "news.approval.approve",
        "news.approval.reject",
        "news.event.dead_letters.resolve",
        "news.event.dead_letters.requeue",
    }
)
RETENTION_POLICY_ARG_NAMES = (
    "raw_source_retention_days",
    "llm_artifact_retention_days",
    "run_artifact_retention_days",
    "report_retention_days",
    "evidence_retention_days",
    "vector_retention_days",
)
SUBSCRIPTION_PROFILE_ENUM = ["research"]


class MCPApplicationService:
    def __init__(
        self,
        *,
        worker_service_factory: Callable[[], Any] | None = None,
        run_service_factory: Callable[[], Any] | None = None,
        report_service_factory: Callable[[], Any] | None = None,
        source_service_factory: Callable[[], Any] | None = None,
        entity_service_factory: Callable[[], Any] | None = None,
        subscription_service_factory: Callable[[], Any] | None = None,
        memory_service_factory: Callable[[], Any] | None = None,
        diagnostic_service_factory: Callable[[], Any] | None = None,
        approval_service_factory: Callable[[], Any] | None = None,
        graph_run_inspection_service_factory: Callable[[], Any] | None = None,
        graph_run_operation_service_factory: Callable[[], Any] | None = None,
        artifact_service_factory: Callable[[], Any] | None = None,
        storage_service_factory: Callable[[], Any] | None = None,
        research_service_factory: Callable[[], Any] | None = None,
        event_operator_service_factory: Callable[[ActorContext], Any] | None = None,
        operator_actor: ActorContext | None = None,
    ) -> None:
        self.worker_service_factory = worker_service_factory or _worker_service_factory
        self.run_service_factory = run_service_factory or _run_service_factory
        self.report_service_factory = report_service_factory or _report_service_factory
        self._source_runtime_provider = None
        if source_service_factory is None:
            from interfaces.services.source_runtime import SourceRuntimeProvider

            self._source_runtime_provider = SourceRuntimeProvider()
            self.source_service_factory = (
                self._source_runtime_provider.source_service_factory
            )
        else:
            self.source_service_factory = source_service_factory
        self.entity_service_factory = entity_service_factory or _entity_service_factory
        self.subscription_service_factory = (
            subscription_service_factory or _subscription_service_factory
        )
        self.memory_service_factory = memory_service_factory or _memory_service_factory
        self.diagnostic_service_factory = diagnostic_service_factory or _diagnostic_service_factory
        self.approval_service_factory = approval_service_factory or _approval_service_factory
        self.graph_run_inspection_service_factory = (
            graph_run_inspection_service_factory or _graph_run_inspection_service_factory
        )
        self.graph_run_operation_service_factory = (
            graph_run_operation_service_factory or _graph_run_operation_service_factory
        )
        self.artifact_service_factory = artifact_service_factory or _artifact_service_factory
        self.storage_service_factory = storage_service_factory or _storage_service_factory
        self.research_service_factory = research_service_factory or _research_service_factory
        self.event_operator_service_factory = (
            event_operator_service_factory or _event_operator_service_factory
        )
        self._operator_actor = operator_actor or _deployment_event_operator_actor()

    def for_actor(self, actor: ActorContext) -> "MCPApplicationService":
        """Return a request-scoped view bound to a transport-authenticated actor."""

        if not isinstance(actor, ActorContext):
            raise TypeError("actor must be ActorContext")
        scoped = copy(self)
        scoped._operator_actor = actor
        return scoped

    def catalog(self) -> MCPCatalog:
        return MCPCatalog(tools=_tools(), resources=_resources(), prompts=_prompts())

    def capability_manifest(self) -> MCPCapabilityManifest:
        catalog = self.catalog()
        return MCPCapabilityManifest(
            version=MCP_CAPABILITY_MANIFEST_VERSION,
            capabilities=_capabilities_from_catalog(catalog),
        )

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
            projected = _project_mcp_error(
                exc,
                operation="get_prompt",
            )
            return MCPPromptGetResult(
                name=name,
                success=False,
                error_type=projected.error_type,
                error_message=projected.error_message,
                error_id=projected.error_id,
            )

    def read_resource(self, uri: str) -> MCPResourceReadResult:
        try:
            event_resource = _event_operator_resource_args(uri)
            if event_resource is not None:
                return self._read_event_operator_resource(uri, event_resource)
            if uri == LATEST_REPORT_RESOURCE_URI:
                return self._read_latest_report_resource()
            report_id = _report_resource_report_id(uri)
            if report_id is not None:
                return self._read_report_resource(uri, report_id)
            artifact_resource = _run_artifact_resource_ids(uri)
            if artifact_resource is not None:
                run_id, artifact_key = artifact_resource
                return self._read_run_artifact_resource(uri, run_id, artifact_key)
            artifact_resource = _artifact_resource_ids(uri)
            if artifact_resource is not None:
                run_id, artifact_key = artifact_resource
                return self._read_run_artifact_resource(uri, run_id, artifact_key)
            memory_resource = _memory_resource_args(uri)
            if memory_resource is not None:
                return self._read_memory_resource(uri, memory_resource)
            run_id = _run_manifest_resource_run_id(uri)
            if run_id is not None:
                return self._read_run_manifest_resource(uri, run_id)
            run_events_resource = _run_events_resource_args(uri)
            if run_events_resource is not None:
                return self._read_run_events_resource(uri, run_events_resource)
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
            retention_plan_args = _storage_retention_plan_resource_args(uri)
            if retention_plan_args is not None:
                return self._read_storage_retention_plan_resource(uri, retention_plan_args)
            if uri == SOURCE_HEALTH_RESOURCE_URI:
                return self._read_source_health_resource()
            worker_status_args = _worker_status_resource_args(uri)
            if worker_status_args is not None:
                return self._read_worker_status_resource(uri, worker_status_args)
            queue_status_args = _queue_status_resource_args(uri)
            if queue_status_args is not None:
                return self._read_queue_status_resource(uri, queue_status_args)
            return MCPResourceReadResult(
                uri=uri,
                success=False,
                error_type="MCPResourceNotFound",
                error_message=f"unknown MCP resource: {uri}",
            )
        except Exception as exc:
            projected = _project_mcp_error(
                exc,
                operation="read_resource",
            )
            return MCPResourceReadResult(
                uri=uri,
                success=False,
                error_type=projected.error_type,
                error_message=projected.error_message,
                error_id=projected.error_id,
            )

    def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> MCPToolCallResult:
        args = arguments or {}
        try:
            if tool_name.startswith("news.event."):
                return self._event_operator_tool(tool_name, args)
            if tool_name == "news.research.analyze_paper":
                return self._research_analyze_paper(args)
            if tool_name == "news.research.paper_analysis":
                return self._research_paper_analysis(args)
            if tool_name == "news.research.reader":
                return self._research_reader(args)
            if tool_name == "news.research.ask":
                return self._research_ask(args)
            if tool_name == "news.research.trace":
                return self._research_trace(args)
            if tool_name == "news.report.latest":
                return self._latest_report()
            if tool_name == "news.report.list":
                return self._report_list(args)
            if tool_name == "news.report.get":
                return self._report_get(args)
            if tool_name == "news.report.search":
                return self._report_search(args)
            if tool_name == "news.report.request_review":
                return self._report_request_review(args)
            if tool_name == "news.report.publish":
                return self._report_publish(args)
            if tool_name == "news.source.health":
                return self._source_health(args)
            if tool_name == "news.source.arxiv.fetch":
                return self._source_arxiv_fetch(args)
            if tool_name == "news.source.github.releases":
                return self._source_github_releases(args)
            if tool_name == "news.entity.list":
                return self._entity_list(args)
            if tool_name == "news.entity.create":
                return self._entity_create(args)
            if tool_name == "news.entity.enable":
                return self._entity_enable(args)
            if tool_name == "news.entity.disable":
                return self._entity_disable(args)
            if tool_name == "news.entity.delete":
                return self._entity_delete(args)
            if tool_name == "news.entity.match_reports":
                return self._entity_match_reports(args)
            if tool_name == "news.subscription.list":
                return self._subscription_list(args)
            if tool_name == "news.subscription.create":
                return self._subscription_create(args)
            if tool_name == "news.subscription.enable":
                return self._subscription_enable(args)
            if tool_name == "news.subscription.disable":
                return self._subscription_disable(args)
            if tool_name == "news.subscription.delete":
                return self._subscription_delete(args)
            if tool_name == "news.memory.recall":
                return self._memory_recall(args)
            if tool_name == "news.memory.reindex":
                return self._memory_reindex(args)
            if tool_name == "news.memory.bootstrap":
                return self._memory_bootstrap(args)
            if tool_name == "news.diagnose":
                return self._diagnose()
            if tool_name == "news.run.show":
                return self._run_show(args)
            if tool_name == "news.run.events":
                return self._run_events(args)
            if tool_name == "news.run.replay":
                return self._run_replay(args)
            if tool_name == "news.run.diagnostics":
                return self._run_diagnostics(args)
            if tool_name == "news.run.cancel":
                return self._run_cancel(args)
            if tool_name == "news.run.health":
                return self._run_health(args)
            if tool_name == "news.run.catalog_health":
                return self._run_catalog_health()
            if tool_name == "news.run.compare":
                return self._run_compare(args)
            if tool_name == "news.run.lineage":
                return self._run_lineage(args)
            if tool_name == "news.run.lineage.upstream":
                return self._run_lineage_upstream(args)
            if tool_name == "news.run.lineage.downstream":
                return self._run_lineage_downstream(args)
            if tool_name == "news.storage.metrics":
                return self._storage_metrics()
            if tool_name == "news.storage.retention.plan":
                return self._storage_retention_plan(args)
            if tool_name == "news.worker.status":
                return self._worker_status(args)
            if tool_name == "news.queue.status":
                return self._queue_status(args)
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
            if tool_name == "news.approval.submit_decision":
                return self._approval_submit_decision(args)
            if tool_name == "news.approval.resume_context":
                return self._approval_resume_context(args)
            return MCPToolCallResult(
                tool_name=tool_name,
                success=False,
                error_type="MCPToolNotFound",
                error_message=f"unknown MCP tool: {tool_name}",
            )
        except Exception as exc:
            projected = _project_mcp_error(
                exc,
                operation="call_tool",
            )
            return MCPToolCallResult(
                tool_name=tool_name,
                success=False,
                error_type=projected.error_type,
                error_message=projected.error_message,
                error_id=projected.error_id,
            )

    def _event_operator_service(self):
        actor = self._operator_actor
        if not isinstance(actor, ActorContext):
            raise PermissionError(
                "event operator MCP access requires an authenticated deployment actor"
            )
        return self.event_operator_service_factory(actor)

    def _event_operator_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
    ) -> MCPToolCallResult:
        _validate_event_operator_tool_args(tool_name, args)
        service = self._event_operator_service()
        if tool_name == "news.event.quarantine.list":
            data = service.list_quarantine(
                reason=_optional_arg(args, "reason"),
                disposition=_optional_arg(args, "disposition"),
                cursor=_optional_arg(args, "cursor"),
                limit=_optional_int_arg(args, "limit", default=100),
            )
        elif tool_name == "news.event.quarantine.get":
            data = service.get_quarantine(_required_arg(args, "quarantine_id"))
        elif tool_name == "news.event.replay_reports.list":
            data = service.list_replay_reports(
                source_stream_id=_optional_arg(args, "source_stream_id"),
                mode=_optional_arg(args, "mode"),
                status=_optional_arg(args, "status"),
                cursor=_optional_arg(args, "cursor"),
                limit=_optional_int_arg(args, "limit", default=100),
            )
        elif tool_name == "news.event.replay_reports.get":
            data = service.get_replay_report(_required_arg(args, "replay_id"))
        elif tool_name == "news.event.dead_letters.list":
            version = args.get("subscription_version")
            data = service.list_dead_letters(
                subscription_id=_optional_arg(args, "subscription_id"),
                subscription_version=(None if version in {None, ""} else int(version)),
                disposition=_optional_arg(args, "disposition"),
                cursor=_optional_arg(args, "cursor"),
                limit=_optional_int_arg(args, "limit", default=100),
            )
        elif tool_name == "news.event.dead_letters.get":
            data = service.get_dead_letter(_required_arg(args, "dead_letter_id"))
        elif tool_name == "news.event.dead_letters.resolve":
            _require_event_operator_confirmation(args)
            data = service.resolve_dead_letter(
                _required_arg(args, "dead_letter_id"),
                operator_reason=_required_arg(args, "operator_reason"),
            )
        elif tool_name == "news.event.dead_letters.requeue":
            _require_event_operator_confirmation(args)
            data = service.requeue_dead_letter(
                _required_arg(args, "dead_letter_id"),
                subscription_id=_required_arg(args, "subscription_id"),
                subscription_version=int(args.get("subscription_version")),
                operator_reason=_required_arg(args, "operator_reason"),
                idempotency_acknowledged=True,
            )
        elif tool_name == "news.event.consumer_status":
            data = service.get_consumer_status(
                _required_arg(args, "subscription_id"),
                subscription_version=int(args.get("subscription_version")),
                stream_id=_required_arg(args, "stream_id"),
            )
        elif tool_name == "news.event.projection_status":
            data = service.get_projection_status(_required_arg(args, "run_id"))
        else:
            return MCPToolCallResult(
                tool_name=tool_name,
                success=False,
                error_type="MCPToolNotFound",
                error_message=f"unknown MCP tool: {tool_name}",
            )
        return MCPToolCallResult(tool_name=tool_name, success=True, data=dict(data))

    def _read_event_operator_resource(
        self,
        uri: str,
        resource: tuple[str, dict[str, Any]],
    ) -> MCPResourceReadResult:
        kind, args = resource
        service = self._event_operator_service()
        if kind == "quarantine_list":
            data = service.list_quarantine(**args)
        elif kind == "quarantine_get":
            data = service.get_quarantine(args["quarantine_id"])
        elif kind == "replay_report_list":
            data = service.list_replay_reports(**args)
        elif kind == "replay_report_get":
            data = service.get_replay_report(args["replay_id"])
        elif kind == "dead_letter_list":
            data = service.list_dead_letters(**args)
        elif kind == "dead_letter_get":
            data = service.get_dead_letter(args["dead_letter_id"])
        elif kind == "consumer_status":
            data = service.get_consumer_status(
                args["subscription_id"],
                subscription_version=args["subscription_version"],
                stream_id=args["stream_id"],
            )
        elif kind == "projection_status":
            data = service.get_projection_status(args["run_id"])
        else:
            raise ValueError("unsupported event operator resource")
        return MCPResourceReadResult(uri=uri, success=True, data=dict(data))

    def _research_analyze_paper(self, args: dict[str, Any]) -> MCPToolCallResult:
        actor = _research_actor_input(args, self._operator_actor)
        result = self.research_service_factory().analyze_paper(
            ResearchAnalyzeInput(
                paper_id=_required_arg(args, "paper_id"),
                source_url=_optional_arg(args, "source_url"),
                pdf_url=_optional_arg(args, "pdf_url"),
                run_id=_optional_arg(args, "run_id"),
                user_id=actor.user_id,
                metadata=dict(args.get("metadata") or {}),
                options=dict(args.get("options") or {}),
                tenant_id=actor.tenant_id,
                memory_namespace=actor.memory_namespace,
            )
        )
        return MCPToolCallResult(
            tool_name="news.research.analyze_paper",
            success=True,
            data=_to_dict(result),
        )

    def _research_paper_analysis(self, args: dict[str, Any]) -> MCPToolCallResult:
        result = self.research_service_factory().get_analysis(
            _required_arg(args, "paper_id"),
            actor=_research_actor_input(args, self._operator_actor),
        )
        return MCPToolCallResult(
            tool_name="news.research.paper_analysis",
            success=True,
            data=_to_dict(result),
        )

    def _research_reader(self, args: dict[str, Any]) -> MCPToolCallResult:
        result = self.research_service_factory().get_reader(
            _required_arg(args, "paper_id"),
            actor=_research_actor_input(args, self._operator_actor),
        )
        return MCPToolCallResult(
            tool_name="news.research.reader",
            success=True,
            data=_to_dict(result),
        )

    def _research_ask(self, args: dict[str, Any]) -> MCPToolCallResult:
        actor = _research_actor_input(args, self._operator_actor)
        result = self.research_service_factory().ask_paper(
            _required_arg(args, "paper_id"),
            ResearchAskInput(
                question=_required_arg(args, "question"),
                locale=_optional_arg(args, "locale"),
                selection=dict(args.get("selection") or {}),
                options=dict(args.get("options") or {}),
                tenant_id=actor.tenant_id,
                user_id=actor.user_id,
                memory_namespace=actor.memory_namespace,
            ),
        )
        return MCPToolCallResult(
            tool_name="news.research.ask",
            success=True,
            data=_to_dict(result),
        )

    def _research_trace(self, args: dict[str, Any]) -> MCPToolCallResult:
        result = self.research_service_factory().get_trace(
            _required_arg(args, "run_id"),
            actor=_research_actor_input(args, self._operator_actor),
        )
        return MCPToolCallResult(
            tool_name="news.research.trace",
            success=True,
            data=_to_dict(result),
        )

    def _latest_report(self) -> MCPToolCallResult:
        record = self.report_service_factory().latest_report()
        return MCPToolCallResult(
            tool_name="news.report.latest",
            success=True,
            data=_to_dict(record),
        )

    def _report_list(self, args: dict[str, Any]) -> MCPToolCallResult:
        result = self.report_service_factory().list_reports(
            limit=_optional_int_arg(args, "limit", default=20),
            graph_id=_optional_arg(args, "graph_id"),
            graph_ids=_optional_text_tuple(args, "graph_ids"),
        )
        return MCPToolCallResult(
            tool_name="news.report.list",
            success=True,
            data=result.to_dict(),
        )

    def _report_get(self, args: dict[str, Any]) -> MCPToolCallResult:
        record = self.report_service_factory().get_report(_required_arg(args, "report_id"))
        return MCPToolCallResult(
            tool_name="news.report.get",
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

    def _report_request_review(self, args: dict[str, Any]) -> MCPToolCallResult:
        report_id = _required_arg(args, "report_id")
        action = self.report_service_factory().request_review(
            report_id,
            requested_by=_optional_arg(args, "requested_by"),
            reason=_optional_arg(args, "reason"),
            metadata=dict(args.get("metadata") or {}),
        )
        approval = self.approval_service_factory().submit_request(
            requested_action="review_report",
            risk_level="low",
            reason=args.get("reason"),
            payload={"report_id": report_id, **dict(args.get("metadata") or {})},
            requested_by=args.get("requested_by"),
        )
        data = action.to_dict()
        data["approval"] = approval.to_dict()
        return MCPToolCallResult(
            tool_name="news.report.request_review",
            success=True,
            data=data,
        )

    def _report_publish(self, args: dict[str, Any]) -> MCPToolCallResult:
        report_id = _required_arg(args, "report_id")
        action = self.report_service_factory().publish_report(
            report_id,
            requested_by=_optional_arg(args, "requested_by"),
            reason=_optional_arg(args, "reason"),
            metadata=dict(args.get("metadata") or {}),
        )
        approval = self.approval_service_factory().submit_request(
            requested_action="publish_report",
            risk_level="high",
            reason=args.get("reason"),
            payload={"report_id": report_id, **dict(args.get("metadata") or {})},
            requested_by=args.get("requested_by"),
        )
        data = action.to_dict()
        data["approval"] = approval.to_dict()
        return MCPToolCallResult(
            tool_name="news.report.publish",
            success=True,
            data=data,
        )

    def _source_health(self, args: dict[str, Any]) -> MCPToolCallResult:
        include_disabled = bool(args.get("include_disabled", False))
        result = self.source_service_factory().source_health(enabled_only=not include_disabled)
        return MCPToolCallResult(
            tool_name="news.source.health",
            success=True,
            data=result.to_dict(),
        )

    def _source_arxiv_fetch(self, args: dict[str, Any]) -> MCPToolCallResult:
        query = str(args.get("query") or "")
        if not query:
            raise ValueError("query is required")
        result = self.source_service_factory().fetch_arxiv(
            query=query,
            limit=int(args.get("limit") or 5),
        )
        return MCPToolCallResult(
            tool_name="news.source.arxiv.fetch",
            success=True,
            data=result.to_dict(),
        )

    def _source_github_releases(self, args: dict[str, Any]) -> MCPToolCallResult:
        repository = str(args.get("repository") or args.get("repo") or "")
        if not repository:
            raise ValueError("repository is required")
        result = self.source_service_factory().fetch_github_releases(
            repository=repository,
            limit=int(args.get("limit") or 5),
        )
        return MCPToolCallResult(
            tool_name="news.source.github.releases",
            success=True,
            data=result.to_dict(),
        )

    def _entity_list(self, args: dict[str, Any]) -> MCPToolCallResult:
        result = self.entity_service_factory().list_entities(
            enabled_only=_optional_bool_arg(args, "enabled_only", default=False),
            kind=_optional_arg(args, "kind"),
        )
        return MCPToolCallResult(
            tool_name="news.entity.list",
            success=True,
            data=result.to_dict(),
        )

    def _entity_create(self, args: dict[str, Any]) -> MCPToolCallResult:
        entity = self.entity_service_factory().create_entity(
            name=_required_arg(args, "name"),
            kind=str(args.get("kind") or "company"),
            aliases=_string_list_arg(args, "aliases"),
            entity_id=_optional_arg(args, "entity_id"),
            enabled=_optional_bool_arg(args, "enabled", default=True),
            metadata=dict(args.get("metadata") or {}),
        )
        return MCPToolCallResult(
            tool_name="news.entity.create",
            success=True,
            data=entity.to_dict(),
        )

    def _entity_enable(self, args: dict[str, Any]) -> MCPToolCallResult:
        entity = self.entity_service_factory().set_enabled(
            _required_arg(args, "entity_id"),
            enabled=True,
        )
        return MCPToolCallResult(
            tool_name="news.entity.enable",
            success=True,
            data=entity.to_dict(),
        )

    def _entity_disable(self, args: dict[str, Any]) -> MCPToolCallResult:
        entity = self.entity_service_factory().set_enabled(
            _required_arg(args, "entity_id"),
            enabled=False,
        )
        return MCPToolCallResult(
            tool_name="news.entity.disable",
            success=True,
            data=entity.to_dict(),
        )

    def _entity_delete(self, args: dict[str, Any]) -> MCPToolCallResult:
        entity_id = _required_arg(args, "entity_id")
        deleted = self.entity_service_factory().delete_entity(entity_id)
        return MCPToolCallResult(
            tool_name="news.entity.delete",
            success=True,
            data={"entity_id": entity_id, "deleted": deleted},
        )

    def _entity_match_reports(self, args: dict[str, Any]) -> MCPToolCallResult:
        result = self.entity_service_factory().match_reports(
            _required_arg(args, "entity_id"),
            artifact_root=str(args.get("artifact_root") or ".newsroom/runs"),
            limit=_optional_int_arg(args, "limit", default=20),
            graph_id=_optional_arg(args, "graph_id"),
            graph_ids=_optional_text_tuple(args, "graph_ids"),
        )
        return MCPToolCallResult(
            tool_name="news.entity.match_reports",
            success=True,
            data=result.to_dict(),
        )

    def _subscription_list(self, args: dict[str, Any]) -> MCPToolCallResult:
        result = self.subscription_service_factory().list_topic_subscriptions(
            enabled_only=_optional_bool_arg(args, "enabled_only", default=False),
            cadence=_optional_arg(args, "cadence"),
        )
        return MCPToolCallResult(
            tool_name="news.subscription.list",
            success=True,
            data=result.to_dict(),
        )

    def _subscription_create(self, args: dict[str, Any]) -> MCPToolCallResult:
        subscription = self.subscription_service_factory().create_topic_subscription(
            topic=_required_arg(args, "topic"),
            cadence=str(args.get("cadence") or "weekly"),
            profile=str(args.get("profile") or "live-offline"),
            source_limit=_optional_int_arg(args, "source_limit", default=5),
            subscription_id=_optional_arg(args, "subscription_id"),
            enabled=_optional_bool_arg(args, "enabled", default=True),
            metadata=dict(args.get("metadata") or {}),
        )
        return MCPToolCallResult(
            tool_name="news.subscription.create",
            success=True,
            data=_to_dict(subscription),
        )

    def _subscription_enable(self, args: dict[str, Any]) -> MCPToolCallResult:
        subscription = self.subscription_service_factory().set_enabled(
            _required_arg(args, "subscription_id"),
            enabled=True,
        )
        return MCPToolCallResult(
            tool_name="news.subscription.enable",
            success=True,
            data=subscription.to_dict(),
        )

    def _subscription_disable(self, args: dict[str, Any]) -> MCPToolCallResult:
        subscription = self.subscription_service_factory().set_enabled(
            _required_arg(args, "subscription_id"),
            enabled=False,
        )
        return MCPToolCallResult(
            tool_name="news.subscription.disable",
            success=True,
            data=subscription.to_dict(),
        )

    def _subscription_delete(self, args: dict[str, Any]) -> MCPToolCallResult:
        subscription_id = _required_arg(args, "subscription_id")
        deleted = self.subscription_service_factory().delete_topic_subscription(subscription_id)
        return MCPToolCallResult(
            tool_name="news.subscription.delete",
            success=True,
            data={"subscription_id": subscription_id, "deleted": deleted},
        )

    def _memory_recall(self, args: dict[str, Any]) -> MCPToolCallResult:
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
            tool_name="news.memory.recall",
            success=True,
            data=result.to_dict(),
        )

    def _memory_reindex(self, args: dict[str, Any]) -> MCPToolCallResult:
        result = self.memory_service_factory().reindex_run(
            _required_arg(args, "run_id"),
            topic=_optional_arg(args, "topic"),
        )
        return MCPToolCallResult(
            tool_name="news.memory.reindex",
            success=True,
            data=result.to_dict(),
        )

    def _memory_bootstrap(self, args: dict[str, Any]) -> MCPToolCallResult:
        collections = _string_list_arg(args, "collections")
        result = self.memory_service_factory().bootstrap_collections(collections or None)
        return MCPToolCallResult(
            tool_name="news.memory.bootstrap",
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
        result = self.graph_run_inspection_service_factory().get_run(run_id)
        return MCPToolCallResult(
            tool_name="news.run.show",
            success=True,
            data=result.to_dict(),
        )

    def _run_events(self, args: dict[str, Any]) -> MCPToolCallResult:
        run_id = str(args.get("run_id") or "")
        if not run_id:
            raise ValueError("run_id is required")
        result = self.graph_run_inspection_service_factory().get_run_events(
            run_id,
            limit=int(args["limit"]) if args.get("limit") is not None else None,
            offset=int(args.get("offset") or 0),
            event_type=_optional_arg(args, "event_type"),
            node_instance_id=_optional_arg(args, "node_instance_id"),
            sequence_cursor=_optional_arg(args, "sequence_cursor"),
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
        result = self.graph_run_inspection_service_factory().replay_run(run_id)
        return MCPToolCallResult(
            tool_name="news.run.replay",
            success=True,
            data=result.to_dict(),
        )

    def _run_diagnostics(self, args: dict[str, Any]) -> MCPToolCallResult:
        run_id = str(args.get("run_id") or "")
        if not run_id:
            raise ValueError("run_id is required")
        result = self.graph_run_inspection_service_factory().get_run_diagnostics(run_id)
        return MCPToolCallResult(
            tool_name="news.run.diagnostics",
            success=True,
            data=result.to_dict(),
        )

    def _run_cancel(self, args: dict[str, Any]) -> MCPToolCallResult:
        actor = self._graph_operation_actor()
        result = self.graph_run_operation_service_factory().cancel_run(
            _required_arg(args, "run_id"),
            reason_code=_required_arg(args, "reason_code"),
            cancellation_id=_optional_arg(args, "cancellation_id"),
            actor=actor,
        )
        return MCPToolCallResult(
            tool_name="news.run.cancel",
            success=True,
            data=result.to_dict(),
        )

    def _graph_operation_actor(self) -> ActorContext:
        actor = self._operator_actor
        if not isinstance(actor, ActorContext):
            raise PermissionError(
                "Graph run mutation requires an authenticated MCP actor"
            )
        return actor

    def _run_health(self, args: dict[str, Any]) -> MCPToolCallResult:
        run_id = str(args.get("run_id") or "")
        if not run_id:
            raise ValueError("run_id is required")
        result = self.graph_run_inspection_service_factory().get_run_health(run_id)
        return MCPToolCallResult(
            tool_name="news.run.health",
            success=True,
            data=result.to_dict(),
        )

    def _run_catalog_health(self) -> MCPToolCallResult:
        result = self.graph_run_inspection_service_factory().get_catalog_health()
        return MCPToolCallResult(
            tool_name="news.run.catalog_health",
            success=True,
            data=result.to_dict(),
        )

    def _run_compare(self, args: dict[str, Any]) -> MCPToolCallResult:
        base_run_id = str(args.get("base_run_id") or "")
        target_run_id = str(args.get("target_run_id") or "")
        if not base_run_id:
            raise ValueError("base_run_id is required")
        if not target_run_id:
            raise ValueError("target_run_id is required")
        result = self.graph_run_inspection_service_factory().compare_runs(
            base_run_id,
            target_run_id,
        )
        return MCPToolCallResult(
            tool_name="news.run.compare",
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

    def _storage_retention_plan(self, args: dict[str, Any]) -> MCPToolCallResult:
        result = self.storage_service_factory().plan_retention(
            policy=_retention_policy_from_args(args),
            run_id=_optional_arg(args, "run_id"),
            now=_optional_datetime_arg(args, "now"),
        )
        return MCPToolCallResult(
            tool_name="news.storage.retention.plan",
            success=True,
            data=result.to_dict(),
        )

    def _worker_status(self, args: dict[str, Any]) -> MCPToolCallResult:
        result = self.worker_service_factory().list_worker_status(
            worker_id=_optional_arg(args, "worker_id"),
            stale_after_seconds=_optional_int_arg(args, "stale_after_seconds", default=60),
        )
        return MCPToolCallResult(
            tool_name="news.worker.status",
            success=True,
            data=result.to_dict(),
        )

    def _queue_status(self, args: dict[str, Any]) -> MCPToolCallResult:
        result = self.worker_service_factory().queue_status(queue_names=_queue_names_from_args(args))
        return MCPToolCallResult(
            tool_name="news.queue.status",
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

    def _approval_submit_decision(self, args: dict[str, Any]) -> MCPToolCallResult:
        decision = str(args.get("decision") or "").strip().lower()
        if decision == "approve":
            result = self.approval_service_factory().approve(
                _approval_id(args),
                decided_by=_decided_by(args),
                reason=args.get("reason"),
            )
        elif decision == "reject":
            result = self.approval_service_factory().reject(
                _approval_id(args),
                decided_by=_decided_by(args),
                reason=args.get("reason"),
            )
        elif decision == "modify":
            result = self.approval_service_factory().modify(
                _approval_id(args),
                decided_by=_decided_by(args),
                modifications=dict(args.get("modifications") or {}),
                reason=args.get("reason"),
            )
        else:
            raise ValueError("decision must be approve, reject, or modify")
        return MCPToolCallResult(
            tool_name="news.approval.submit_decision",
            success=True,
            data=result.to_dict(),
        )

    def _approval_resume_context(self, args: dict[str, Any]) -> MCPToolCallResult:
        result = self.approval_service_factory().build_resume_context(
            _approval_id(args),
            decision_key=str(args.get("decision_key") or "human_review_decision"),
        )
        return MCPToolCallResult(
            tool_name="news.approval.resume_context",
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
        result = self.graph_run_inspection_service_factory().get_run(run_id)
        return MCPResourceReadResult(
            uri=uri,
            success=True,
            data=result.to_dict(),
        )

    def _read_run_events_resource(
        self,
        uri: str,
        args: dict[str, Any],
    ) -> MCPResourceReadResult:
        run_id = str(args.pop("run_id"))
        allowed = {
            "limit",
            "offset",
            "event_type",
            "node_instance_id",
            "sequence_cursor",
        }
        unknown = set(args) - allowed
        if unknown:
            raise ValueError(f"unsupported run events resource parameter: {sorted(unknown)[0]}")
        result = self.graph_run_inspection_service_factory().get_run_events(
            run_id,
            limit=(int(args["limit"]) if args.get("limit") is not None else None),
            offset=int(args.get("offset") or 0),
            event_type=_optional_arg(args, "event_type"),
            node_instance_id=_optional_arg(args, "node_instance_id"),
            sequence_cursor=_optional_arg(args, "sequence_cursor"),
        )
        return MCPResourceReadResult(
            uri=uri,
            success=True,
            data=result.to_dict(),
        )

    def _read_run_replay_resource(self, uri: str, run_id: str) -> MCPResourceReadResult:
        result = self.graph_run_inspection_service_factory().replay_run(run_id)
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

    def _read_storage_retention_plan_resource(
        self,
        uri: str,
        args: dict[str, Any],
    ) -> MCPResourceReadResult:
        result = self.storage_service_factory().plan_retention(
            policy=_retention_policy_from_args(args),
            run_id=_optional_arg(args, "run_id"),
            now=_optional_datetime_arg(args, "now"),
        )
        return MCPResourceReadResult(
            uri=uri,
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

    def _read_memory_resource(
        self,
        uri: str,
        args: dict[str, Any],
    ) -> MCPResourceReadResult:
        result = self.memory_service_factory().get_document(
            _required_arg(args, "document_id"),
            collection=str(args.get("collection") or DEFAULT_MEMORY_COLLECTION),
        )
        return MCPResourceReadResult(
            uri=uri,
            success=True,
            data=result.to_dict(),
        )

    def _read_worker_status_resource(
        self,
        uri: str,
        args: dict[str, Any],
    ) -> MCPResourceReadResult:
        result = self.worker_service_factory().list_worker_status(
            worker_id=_optional_arg(args, "worker_id"),
            stale_after_seconds=_optional_int_arg(args, "stale_after_seconds", default=60),
        )
        return MCPResourceReadResult(
            uri=uri,
            success=True,
            data=result.to_dict(),
        )

    def _read_queue_status_resource(
        self,
        uri: str,
        args: dict[str, Any],
    ) -> MCPResourceReadResult:
        result = self.worker_service_factory().queue_status(queue_names=_queue_names_from_args(args))
        return MCPResourceReadResult(
            uri=uri,
            success=True,
            data=result.to_dict(),
        )


def _tools() -> list[MCPTool]:
    return [
        *_event_operator_tools(),
        MCPTool(
            name="news.research.analyze_paper",
            title="Analyze research paper",
            description="Run Harness-controlled Research paper analysis through ResearchApplicationService.",
            input_schema={
                "type": "object",
                "required": ["paper_id"],
                "properties": {
                    "paper_id": {"type": "string"},
                    "source_url": {"type": "string"},
                    "pdf_url": {"type": "string"},
                    "run_id": {"type": "string"},
                    "user_id": {"type": "string"},
                    "tenant_id": {"type": "string"},
                    "memory_namespace": {"type": "string"},
                    "metadata": {"type": "object"},
                    "options": {"type": "object"},
                },
            },
        ),
        MCPTool(
            name="news.research.paper_analysis",
            title="Read research analysis",
            description="Read the latest accepted Research analysis for a paper.",
            input_schema={
                "type": "object",
                "required": ["paper_id"],
                "properties": {
                    "paper_id": {"type": "string"},
                    "tenant_id": {"type": "string"},
                    "user_id": {"type": "string"},
                    "memory_namespace": {"type": "string"},
                },
            },
        ),
        MCPTool(
            name="news.research.reader",
            title="Read research reader payload",
            description="Read the latest accepted Research reader payload for a paper.",
            input_schema={
                "type": "object",
                "required": ["paper_id"],
                "properties": {
                    "paper_id": {"type": "string"},
                    "tenant_id": {"type": "string"},
                    "user_id": {"type": "string"},
                    "memory_namespace": {"type": "string"},
                },
            },
        ),
        MCPTool(
            name="news.research.ask",
            title="Ask research paper",
            description="Ask an evidence-grounded question against an accepted Research paper analysis.",
            input_schema={
                "type": "object",
                "required": ["paper_id", "question"],
                "properties": {
                    "paper_id": {"type": "string"},
                    "question": {"type": "string"},
                    "locale": {"type": "string"},
                    "tenant_id": {"type": "string"},
                    "user_id": {"type": "string"},
                    "memory_namespace": {"type": "string"},
                    "selection": {"type": "object"},
                    "options": {"type": "object"},
                },
            },
        ),
        MCPTool(
            name="news.research.trace",
            title="Read research trace",
            description="Read Harness trace metadata for a Research run.",
            input_schema={
                "type": "object",
                "required": ["run_id"],
                "properties": {
                    "run_id": {"type": "string"},
                    "tenant_id": {"type": "string"},
                    "user_id": {"type": "string"},
                    "memory_namespace": {"type": "string"},
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
            name="news.report.list",
            title="List reports",
            description="List persisted report artifacts through ReportApplicationService.",
            input_schema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1},
                    "graph_id": {"type": "string"},
                    "graph_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
        ),
        MCPTool(
            name="news.report.get",
            title="Get report",
            description="Return one persisted report artifact through ReportApplicationService.",
            input_schema={
                "type": "object",
                "required": ["report_id"],
                "properties": {"report_id": {"type": "string"}},
            },
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
            name="news.report.request_review",
            title="Request report review",
            description="Request human review for a persisted report through application services.",
            input_schema={
                "type": "object",
                "required": ["report_id"],
                "properties": {
                    "report_id": {"type": "string"},
                    "requested_by": {"type": "string"},
                    "reason": {"type": "string"},
                    "metadata": {"type": "object"},
                },
            },
        ),
        MCPTool(
            name="news.report.publish",
            title="Request report publish",
            description="Create an approval-gated publish request for a persisted report.",
            input_schema={
                "type": "object",
                "required": ["report_id"],
                "properties": {
                    "report_id": {"type": "string"},
                    "requested_by": {"type": "string"},
                    "reason": {"type": "string"},
                    "metadata": {"type": "object"},
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
            name="news.source.arxiv.fetch",
            title="Fetch arXiv source preview",
            description="Fetch arXiv source items through SourceApplicationService.",
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
            name="news.source.github.releases",
            title="Fetch GitHub release source preview",
            description="Fetch GitHub release source items through SourceApplicationService.",
            input_schema={
                "type": "object",
                "required": ["repository"],
                "properties": {
                    "repository": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1},
                },
            },
        ),
        MCPTool(
            name="news.entity.list",
            title="List tracked entities",
            description="List tracked entities through EntityTrackingApplicationService.",
            input_schema={
                "type": "object",
                "properties": {
                    "enabled_only": {"type": "boolean"},
                    "kind": {
                        "type": "string",
                        "enum": ["company", "project", "person", "organization"],
                    },
                },
            },
        ),
        MCPTool(
            name="news.entity.create",
            title="Create tracked entity",
            description="Create or update a tracked entity through EntityTrackingApplicationService.",
            input_schema={
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": ["company", "project", "person", "organization"],
                    },
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "entity_id": {"type": "string"},
                    "enabled": {"type": "boolean"},
                    "metadata": {"type": "object"},
                },
            },
        ),
        MCPTool(
            name="news.entity.enable",
            title="Enable tracked entity",
            description="Enable a tracked entity.",
            input_schema={
                "type": "object",
                "required": ["entity_id"],
                "properties": {"entity_id": {"type": "string"}},
            },
        ),
        MCPTool(
            name="news.entity.disable",
            title="Disable tracked entity",
            description="Disable a tracked entity.",
            input_schema={
                "type": "object",
                "required": ["entity_id"],
                "properties": {"entity_id": {"type": "string"}},
            },
        ),
        MCPTool(
            name="news.entity.delete",
            title="Delete tracked entity",
            description="Delete a tracked entity.",
            input_schema={
                "type": "object",
                "required": ["entity_id"],
                "properties": {"entity_id": {"type": "string"}},
            },
        ),
        MCPTool(
            name="news.entity.match_reports",
            title="Match entity reports",
            description="Match a tracked entity against persisted reports.",
            input_schema={
                "type": "object",
                "required": ["entity_id"],
                "properties": {
                    "entity_id": {"type": "string"},
                    "artifact_root": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1},
                    "graph_id": {"type": "string"},
                    "graph_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
        ),
        MCPTool(
            name="news.subscription.list",
            title="List topic subscriptions",
            description="List topic subscriptions through SubscriptionApplicationService.",
            input_schema={
                "type": "object",
                "properties": {
                    "enabled_only": {"type": "boolean"},
                    "cadence": {"type": "string", "enum": ["daily", "weekly"]},
                },
            },
        ),
        MCPTool(
            name="news.subscription.create",
            title="Create topic subscription",
            description="Create or update a topic subscription through SubscriptionApplicationService.",
            input_schema={
                "type": "object",
                "required": ["topic"],
                "properties": {
                    "topic": {"type": "string"},
                    "cadence": {"type": "string", "enum": ["daily", "weekly"]},
                    "profile": {"type": "string", "enum": SUBSCRIPTION_PROFILE_ENUM},
                    "source_limit": {"type": "integer", "minimum": 1},
                    "subscription_id": {"type": "string"},
                    "enabled": {"type": "boolean"},
                    "metadata": {"type": "object"},
                },
            },
        ),
        MCPTool(
            name="news.subscription.enable",
            title="Enable topic subscription",
            description="Enable a topic subscription.",
            input_schema={
                "type": "object",
                "required": ["subscription_id"],
                "properties": {"subscription_id": {"type": "string"}},
            },
        ),
        MCPTool(
            name="news.subscription.disable",
            title="Disable topic subscription",
            description="Disable a topic subscription.",
            input_schema={
                "type": "object",
                "required": ["subscription_id"],
                "properties": {"subscription_id": {"type": "string"}},
            },
        ),
        MCPTool(
            name="news.subscription.delete",
            title="Delete topic subscription",
            description="Delete a topic subscription.",
            input_schema={
                "type": "object",
                "required": ["subscription_id"],
                "properties": {"subscription_id": {"type": "string"}},
            },
        ),
        MCPTool(
            name="news.memory.recall",
            title="Recall vector memory",
            description="Recall vector memory through MemoryApplicationService.",
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
            name="news.memory.reindex",
            title="Reindex run memory",
            description="Reindex a completed run into vector memory through MemoryApplicationService.",
            input_schema={
                "type": "object",
                "required": ["run_id"],
                "properties": {
                    "run_id": {"type": "string"},
                    "topic": {"type": "string"},
                },
            },
        ),
        MCPTool(
            name="news.memory.bootstrap",
            title="Bootstrap vector memory",
            description="Create or verify vector memory collections through MemoryApplicationService.",
            input_schema={
                "type": "object",
                "properties": {
                    "collections": {
                        "type": "array",
                        "items": {"type": "string"},
                    }
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
            description="Read one Graph run manifest through GraphRunInspectionService.",
            input_schema={
                "type": "object",
                "required": ["run_id"],
                "properties": {"run_id": {"type": "string"}},
            },
        ),
        MCPTool(
            name="news.run.events",
            title="Show run events",
            description="Read structured Graph run events through GraphRunInspectionService.",
            input_schema={
                "type": "object",
                "required": ["run_id"],
                "properties": {
                    "run_id": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1},
                    "offset": {"type": "integer", "minimum": 0},
                    "event_type": {"type": "string"},
                    "node_instance_id": {"type": "string"},
                    "sequence_cursor": {"type": "string"},
                },
            },
        ),
        MCPTool(
            name="news.run.replay",
            title="Replay run artifacts",
            description="Read a Graph run replay bundle through GraphRunInspectionService.",
            input_schema={
                "type": "object",
                "required": ["run_id"],
                "properties": {"run_id": {"type": "string"}},
            },
        ),
        MCPTool(
            name="news.run.diagnostics",
            title="Inspect run diagnostics",
            description="Read Graph run diagnostics through GraphRunInspectionService.",
            input_schema={
                "type": "object",
                "required": ["run_id"],
                "properties": {"run_id": {"type": "string"}},
            },
        ),
        MCPTool(
            name="news.run.cancel",
            title="Cancel run",
            description="Request Graph run cancellation through GraphRunOperationApplicationService.",
            input_schema={
                "type": "object",
                "required": ["run_id", "reason_code"],
                "properties": {
                    "run_id": {"type": "string"},
                    "reason_code": {"type": "string"},
                    "cancellation_id": {"type": "string"},
                },
            },
        ),
        MCPTool(
            name="news.run.health",
            title="Inspect run health",
            description="Read Graph run health through GraphRunInspectionService.",
            input_schema={
                "type": "object",
                "required": ["run_id"],
                "properties": {"run_id": {"type": "string"}},
            },
        ),
        MCPTool(
            name="news.run.catalog_health",
            title="Inspect run catalog health",
            description="Read Graph run catalog health through GraphRunInspectionService.",
            input_schema={"type": "object", "properties": {}},
        ),
        MCPTool(
            name="news.run.compare",
            title="Compare Graph runs",
            description="Compare two Graph runs through GraphRunInspectionService.",
            input_schema={
                "type": "object",
                "required": ["base_run_id", "target_run_id"],
                "properties": {
                    "base_run_id": {"type": "string"},
                    "target_run_id": {"type": "string"},
                },
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
            name="news.storage.retention.plan",
            title="Plan storage retention",
            description="Read a non-destructive storage retention plan through StorageApplicationService.",
            input_schema={
                "type": "object",
                "properties": {
                    "run_id": {"type": "string"},
                    "now": {"type": "string", "format": "date-time"},
                    "raw_source_retention_days": {"type": "integer", "minimum": 0},
                    "llm_artifact_retention_days": {"type": "integer", "minimum": 0},
                    "run_artifact_retention_days": {"type": "integer", "minimum": 0},
                    "report_retention_days": {"type": "integer", "minimum": 0},
                    "evidence_retention_days": {"type": "integer", "minimum": 0},
                    "vector_retention_days": {"type": "integer", "minimum": 0},
                },
            },
        ),
        MCPTool(
            name="news.worker.status",
            title="Read worker status",
            description="Read worker heartbeat status through WorkerApplicationService.",
            input_schema={
                "type": "object",
                "properties": {
                    "worker_id": {"type": "string"},
                    "stale_after_seconds": {"type": "integer", "minimum": 0},
                },
            },
        ),
        MCPTool(
            name="news.queue.status",
            title="Read queue status",
            description="Read Redis worker queue status through WorkerApplicationService.",
            input_schema={
                "type": "object",
                "properties": {
                    "queue_names": {
                        "type": "array",
                        "items": {"type": "string"},
                    }
                },
            },
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
        MCPTool(
            name="news.approval.submit_decision",
            title="Submit approval decision",
            description="Submit an approve, reject, or modify decision for a pending approval request.",
            input_schema={
                "type": "object",
                "required": ["approval_id", "decision", "decided_by"],
                "properties": {
                    "approval_id": {"type": "string"},
                    "decision": {
                        "type": "string",
                        "enum": ["approve", "reject", "modify"],
                    },
                    "decided_by": {"type": "string"},
                    "modifications": {"type": "object"},
                    "reason": {"type": "string"},
                },
            },
        ),
        MCPTool(
            name="news.approval.resume_context",
            title="Build approval resume context",
            description="Build DataBuffer updates and resume metadata from a decided approval.",
            input_schema={
                "type": "object",
                "required": ["approval_id"],
                "properties": {
                    "approval_id": {"type": "string"},
                    "decision_key": {
                        "type": "string",
                        "default": "human_review_decision",
                    },
                },
            },
        ),
    ]


def _event_operator_tools() -> list[MCPTool]:
    page_properties = {
        "cursor": {"type": "string"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
    }
    confirm_schema = {
        "confirm": {"type": "boolean", "const": True},
        "operator_reason": {"type": "string", "minLength": 1, "maxLength": 512},
    }
    return [
        MCPTool(
            name="news.event.quarantine.list",
            title="List event quarantine",
            description="List redacted tenant-scoped event quarantine records.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "reason": {"type": "string"},
                    "disposition": {"type": "string"},
                    **page_properties,
                },
            },
        ),
        MCPTool(
            name="news.event.quarantine.get",
            title="Get event quarantine record",
            description="Read one redacted tenant-scoped quarantine record.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["quarantine_id"],
                "properties": {"quarantine_id": {"type": "string"}},
            },
        ),
        MCPTool(
            name="news.event.replay_reports.list",
            title="List event replay reports",
            description="List tenant-scoped deterministic replay reports.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "source_stream_id": {"type": "string"},
                    "mode": {"type": "string"},
                    "status": {"type": "string"},
                    **page_properties,
                },
            },
        ),
        MCPTool(
            name="news.event.replay_reports.get",
            title="Get event replay report",
            description="Read one tenant-scoped deterministic replay report.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["replay_id"],
                "properties": {"replay_id": {"type": "string"}},
            },
        ),
        MCPTool(
            name="news.event.dead_letters.list",
            title="List event dead letters",
            description="List redacted tenant-scoped event dead letters.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "subscription_id": {"type": "string"},
                    "subscription_version": {"type": "integer", "minimum": 1},
                    "disposition": {"type": "string"},
                    **page_properties,
                },
            },
        ),
        MCPTool(
            name="news.event.dead_letters.get",
            title="Get event dead letter",
            description="Read one redacted tenant-scoped event dead letter.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["dead_letter_id"],
                "properties": {"dead_letter_id": {"type": "string"}},
            },
        ),
        MCPTool(
            name="news.event.dead_letters.resolve",
            title="Resolve event dead letter",
            description="Terminally resolve one tenant-scoped dead letter.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["dead_letter_id", "operator_reason", "confirm"],
                "properties": {
                    "dead_letter_id": {"type": "string"},
                    **confirm_schema,
                },
            },
        ),
        MCPTool(
            name="news.event.dead_letters.requeue",
            title="Requeue event dead letter",
            description=(
                "Schedule an idempotency-checked late-repair generation through "
                "the attached durable consumer runtime."
            ),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "dead_letter_id",
                    "subscription_id",
                    "subscription_version",
                    "operator_reason",
                    "confirm",
                ],
                "properties": {
                    "dead_letter_id": {"type": "string"},
                    "subscription_id": {"type": "string"},
                    "subscription_version": {"type": "integer", "minimum": 1},
                    **confirm_schema,
                },
            },
        ),
        MCPTool(
            name="news.event.consumer_status",
            title="Read event consumer status",
            description="Read tenant-scoped delivery lag and checkpoint status.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["subscription_id", "subscription_version", "stream_id"],
                "properties": {
                    "subscription_id": {"type": "string"},
                    "subscription_version": {"type": "integer", "minimum": 1},
                    "stream_id": {"type": "string"},
                },
            },
        ),
        MCPTool(
            name="news.event.projection_status",
            title="Read event projection status",
            description="Verify a run projection against tenant-scoped durable history.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["run_id"],
                "properties": {"run_id": {"type": "string"}},
            },
        ),
    ]


def _resources() -> list[MCPResource]:
    return [
        *_event_operator_resources(),
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
            description="Graph run manifest by run id.",
        ),
        MCPResource(
            uri=RUN_EVENTS_RESOURCE_TEMPLATE,
            name="Run Events",
            description="Structured Graph run events by run id.",
        ),
        MCPResource(
            uri=RUN_REPLAY_RESOURCE_TEMPLATE,
            name="Run Replay",
            description="Graph run replay bundle by run id.",
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
            description="Manifest-listed Graph artifact by run id and artifact key.",
        ),
        MCPResource(
            uri=ARTIFACT_RESOURCE_TEMPLATE,
            name="Artifact",
            description="Manifest-listed artifact using run_id:artifact_key or run_id query.",
        ),
        MCPResource(
            uri=MEMORY_RESOURCE_TEMPLATE,
            name="Memory Document",
            description="Vector memory document by document id.",
        ),
        MCPResource(
            uri=STORAGE_METRICS_RESOURCE_URI,
            name="Storage Metrics",
            description="Local storage metrics.",
        ),
        MCPResource(
            uri=STORAGE_RETENTION_PLAN_RESOURCE_URI,
            name="Storage Retention Plan",
            description="Read-only local storage retention plan.",
        ),
        MCPResource(
            uri=SOURCE_HEALTH_RESOURCE_URI,
            name="Source Health",
            description="Current source health view.",
        ),
        MCPResource(
            uri=WORKERS_RESOURCE_TEMPLATE,
            name="Worker Status",
            description="Current worker heartbeat status.",
        ),
        MCPResource(
            uri=WORKER_RESOURCE_TEMPLATE,
            name="Worker Detail",
            description="Worker heartbeat status by worker id.",
        ),
        MCPResource(
            uri=QUEUES_RESOURCE_URI,
            name="Queue Status",
            description="Current Redis worker queue status.",
        ),
    ]


def _event_operator_resources() -> list[MCPResource]:
    return [
        MCPResource(
            uri=EVENT_QUARANTINE_RESOURCE_URI,
            name="Event Quarantine",
            description="Redacted tenant-scoped event quarantine records.",
        ),
        MCPResource(
            uri=EVENT_QUARANTINE_RESOURCE_TEMPLATE,
            name="Event Quarantine Record",
            description="One redacted tenant-scoped quarantine record.",
        ),
        MCPResource(
            uri=EVENT_REPLAY_REPORTS_RESOURCE_URI,
            name="Event Replay Reports",
            description="Tenant-scoped deterministic replay reports.",
        ),
        MCPResource(
            uri=EVENT_REPLAY_REPORT_RESOURCE_TEMPLATE,
            name="Event Replay Report",
            description="One tenant-scoped deterministic replay report.",
        ),
        MCPResource(
            uri=EVENT_DEAD_LETTERS_RESOURCE_URI,
            name="Event Dead Letters",
            description="Redacted tenant-scoped event dead letters.",
        ),
        MCPResource(
            uri=EVENT_DEAD_LETTER_RESOURCE_TEMPLATE,
            name="Event Dead Letter",
            description="One redacted tenant-scoped event dead letter.",
        ),
        MCPResource(
            uri=EVENT_CONSUMER_STATUS_RESOURCE_TEMPLATE,
            name="Event Consumer Status",
            description="Tenant-scoped event consumer lag and checkpoint status.",
        ),
        MCPResource(
            uri=EVENT_PROJECTION_STATUS_RESOURCE_TEMPLATE,
            name="Event Projection Status",
            description="Run projection status against tenant-scoped durable history.",
        ),
    ]


def _capabilities_from_catalog(catalog: MCPCatalog) -> list[MCPCapability]:
    capabilities: list[MCPCapability] = []
    capabilities.extend(_tool_capability(tool) for tool in catalog.tools)
    capabilities.extend(_resource_capability(resource) for resource in catalog.resources)
    capabilities.extend(_prompt_capability(prompt) for prompt in catalog.prompts)
    return capabilities


def _tool_capability(tool: MCPTool) -> MCPCapability:
    read_only = _tool_is_read_only(tool.name)
    requires_confirmation = _tool_requires_confirmation(tool.name)
    side_effect_level = _tool_side_effect_level(tool.name, read_only=read_only)
    return MCPCapability(
        name=tool.name,
        kind="tool",
        title=tool.title,
        description=tool.description,
        permission=_tool_permission(tool.name),
        read_only=read_only,
        category=_mcp_category(tool.name),
        risk_level=_tool_risk_level(tool.name),
        requires_approval=_tool_requires_approval(tool.name),
        input_schema=tool.input_schema,
        metadata={
            "requires_confirmation": requires_confirmation,
            "side_effect_level": side_effect_level,
            "side_effect": side_effect_level,
        },
    )


def _resource_capability(resource: MCPResource) -> MCPCapability:
    return MCPCapability(
        name=resource.uri,
        kind="resource",
        title=resource.name,
        description=resource.description,
        permission=_resource_permission(resource.uri),
        read_only=True,
        category=_mcp_category(resource.uri),
        risk_level="low",
        uri_template=resource.uri,
        output_mime_type=resource.mime_type,
        metadata={"redacted": True},
    )


def _prompt_capability(prompt: MCPPrompt) -> MCPCapability:
    return MCPCapability(
        name=prompt.name,
        kind="prompt",
        title=prompt.name,
        description=prompt.description,
        permission="mcp:read",
        read_only=True,
        category=_mcp_category(prompt.name),
        risk_level="low",
        input_schema=prompt.arguments_schema,
        metadata={"side_effect": "none"},
    )


def tool_required_permission(tool_name: str) -> str:
    return _tool_permission(tool_name)


def resource_required_permission(uri: str) -> str:
    return _resource_permission(uri)


def is_event_operator_resource_uri(uri: str) -> bool:
    try:
        parsed = urlsplit(uri)
    except ValueError:
        return False
    return (
        parsed.scheme.casefold() == "news"
        and parsed.netloc.casefold() == "events"
    )


def _project_mcp_error(
    exc: Exception,
    *,
    operation: str,
) -> PublicErrorProjection:
    if isinstance(exc, ResearchActorAuthorizationError):
        return PublicErrorProjection(
            "ResearchActorAuthorizationError",
            "Research actor scope does not match the authenticated principal",
        )
    if isinstance(exc, ResearchServiceError):
        if exc.code == "quality_gate_failed":
            return PublicErrorProjection(
                "ResearchQualityGateError",
                "research quality gate failed",
            )
        if exc.code == "research_runtime_unavailable":
            return PublicErrorProjection(
                "ResearchRuntimeUnavailableError",
                "research runtime is unavailable",
            )
        if exc.code == "research_configuration_invalid":
            return PublicErrorProjection(
                "ResearchConfigurationError",
                "research runtime configuration is invalid",
            )
        if str(exc.details.get("error_type") or "") == "ResearchSourceError":
            return PublicErrorProjection(
                "ResearchSourceError",
                "research source acquisition failed",
            )
    if isinstance(exc, EventAuthorizationError):
        return PublicErrorProjection(
            "EventAuthorizationError",
            "event operator action is not authorized",
        )
    if isinstance(exc, EventOperationNotFoundError):
        return PublicErrorProjection(
            "EventOperationNotFoundError",
            "event operator resource not found",
        )
    if isinstance(exc, EventOperationCapabilityUnavailableError):
        return PublicErrorProjection(
            "EventOperationCapabilityUnavailableError",
            "event operator capability is unavailable",
        )
    if isinstance(exc, EventStoreUnavailableError):
        return PublicErrorProjection(
            "EventStoreUnavailableError",
            "event store is unavailable",
        )
    if isinstance(exc, EventContractError):
        return PublicErrorProjection(
            "EventContractError",
            "event operator data conflicts with the durable event contract",
        )
    if isinstance(exc, EventRuntimeError):
        return PublicErrorProjection(
            "EventRuntimeError",
            "event runtime operation failed",
        )
    return project_public_error(exc, context="mcp", operation=operation)


def _tool_permission(tool_name: str) -> str:
    if tool_name.startswith("news.event."):
        return (
            "events:operate"
            if tool_name in {
                "news.event.dead_letters.resolve",
                "news.event.dead_letters.requeue",
            }
            else "events:read"
        )
    if tool_name.startswith("news.report.") and tool_name.endswith(".publish"):
        return "manage:approvals"
    if tool_name in {"news.report.request_review"}:
        return "manage:approvals"
    if tool_name.startswith("news.approval."):
        return "manage:approvals" if not tool_name.endswith((".list", ".get")) else "read:reports"
    if tool_name == "news.research.analyze_paper":
        return "write:runs"
    if tool_name.startswith("news.research."):
        return "read:reports"
    if tool_name == "news.run.cancel":
        return "write:runs"
    if tool_name.startswith("news.run."):
        return "read:reports"
    if tool_name.startswith("news.report."):
        return "read:reports"
    if tool_name.startswith("news.source."):
        return "read:reports"
    if tool_name.startswith("news.memory."):
        return "read:reports"
    if tool_name.startswith("news.entity."):
        return "read:reports" if _tool_is_read_only(tool_name) else "write:runs"
    if tool_name.startswith("news.subscription."):
        return "read:reports" if _tool_is_read_only(tool_name) else "manage:schedules"
    if tool_name.startswith("news.storage."):
        return "admin:storage"
    if tool_name.startswith("news.worker.") or tool_name.startswith("news.queue."):
        return "read:reports"
    if tool_name == "news.diagnose":
        return "admin:diagnose"
    return "read:reports"


def _resource_permission(uri: str) -> str:
    if is_event_operator_resource_uri(uri):
        return "events:read"
    if uri.startswith("news://reports/"):
        return "read:reports"
    if uri.startswith("news://runs/") or uri.startswith("news://artifacts/"):
        return "read:reports"
    if uri.startswith("news://memory/"):
        return "read:reports"
    if uri.startswith("news://storage/"):
        return "admin:storage"
    if uri.startswith("news://sources/"):
        return "read:reports"
    if uri.startswith("news://workers") or uri.startswith("news://queues"):
        return "read:reports"
    return "read:reports"


def _mcp_category(name: str) -> str:
    value = name.removeprefix("news.").removeprefix("news://")
    if value.startswith("event.") or value.startswith("events/"):
        return "events"
    if value.startswith("research."):
        return "research"
    if value.startswith("run.") or value.startswith("runs/") or value.startswith("artifacts/"):
        return "runs"
    if value.startswith("report.") or value.startswith("reports/"):
        return "reports"
    if value.startswith("source.") or value.startswith("sources/"):
        return "sources"
    if value.startswith("memory.") or value.startswith("memory/"):
        return "memory"
    if value.startswith("infrastructure.storage.") or value.startswith("storage/"):
        return "storage"
    if value.startswith("worker.") or value.startswith("workers"):
        return "workers"
    if value.startswith("queue.") or value.startswith("queues"):
        return "workers"
    if value.startswith("approval."):
        return "approvals"
    if value.startswith("entity."):
        return "entities"
    if value.startswith("subscription."):
        return "subscriptions"
    if value.startswith("diagnose"):
        return "diagnostics"
    return "mcp"


def _tool_is_read_only(tool_name: str) -> bool:
    if tool_name in {
        "news.event.dead_letters.resolve",
        "news.event.dead_letters.requeue",
    }:
        return False
    if tool_name == "news.research.analyze_paper":
        return False
    if tool_name == "news.run.cancel":
        return False
    write_markers = (
        ".enqueue",
        ".run",
        ".create",
        ".enable",
        ".disable",
        ".delete",
        ".reindex",
        ".bootstrap",
        ".request_review",
        ".publish",
        ".submit",
        ".approve",
        ".reject",
        ".modify",
        ".submit_decision",
    )
    return not any(tool_name.endswith(marker) for marker in write_markers)


def _tool_requires_approval(tool_name: str) -> bool:
    return tool_name in {"news.report.publish", "news.report.request_review"}


def _tool_requires_confirmation(tool_name: str) -> bool:
    return tool_name in DANGEROUS_MCP_TOOLS


def _tool_risk_level(tool_name: str) -> Literal["low", "medium", "high"]:
    if _tool_requires_approval(tool_name) or _tool_requires_confirmation(tool_name):
        return "high"
    if _tool_is_read_only(tool_name):
        return "low"
    return "medium"


def _tool_side_effect_level(tool_name: str, *, read_only: bool) -> str:
    if _tool_requires_confirmation(tool_name):
        return "external_write"
    return "none" if read_only else "application_service_write"


def _prompts() -> list[MCPPrompt]:
    return [
        MCPPrompt(
            name="news.research.paper_briefing",
            description="Prepare a grounded Research paper briefing prompt.",
            arguments_schema={
                "type": "object",
                "properties": {
                    "paper_id": {"type": "string"},
                    "question": {"type": "string"},
                },
            },
        ),
        MCPPrompt(
            name="news.report.review",
            description="Review a generated report for evidence coverage and clarity.",
            arguments_schema={"type": "object", "properties": {"report_id": {"type": "string"}}},
        ),
        MCPPrompt(
            name="news.run.diagnose",
            description="Diagnose a Graph run and propose remediation steps.",
            arguments_schema={"type": "object", "properties": {"run_id": {"type": "string"}}},
        ),
        MCPPrompt(
            name="news.source.triage",
            description="Triage source health and reliability issues.",
            arguments_schema={"type": "object", "properties": {"source_id": {"type": "string"}}},
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
        "news.research.paper_briefing": {
            "description": "Prepare a grounded Research paper briefing prompt.",
            "text": (
                "Prepare a concise Research paper briefing for paper {paper_id}.\n"
                "Focus question: {question}\n"
                "Use only accepted Research evidence refs and separate claims from interpretation."
            ),
        },
        "news.report.review": {
            "description": "Review a generated report for evidence coverage and clarity.",
            "text": (
                "Review report {report_id}.\n"
                "Check evidence coverage, citation clarity, unsupported claims, and rewrite risks. "
                "Return concise findings and recommended fixes."
            ),
        },
        "news.run.diagnose": {
            "description": "Diagnose a Graph run and propose remediation steps.",
            "text": (
                "Diagnose Graph run {run_id}.\n"
                "Summarize failed nodes, missing artifacts, terminal states, and safe recovery options."
            ),
        },
        "news.source.triage": {
            "description": "Triage source health and reliability issues.",
            "text": (
                "Triage source {source_id}.\n"
                "Review recent failures, cooldown state, reliability, and remediation steps."
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
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    if is_dataclass(value):
        return asdict(cast(Any, value))
    if isinstance(value, dict):
        return dict(value)
    raise TypeError(f"value is not JSON-safe: {type(value).__name__}")


def _worker_service_factory():
    from interfaces.services.worker_service import WorkerApplicationService

    return WorkerApplicationService()


def _run_service_factory():
    from interfaces.services.run_service import RunApplicationService

    return RunApplicationService()


def _research_service_factory():
    from interfaces.composition.research import build_research_application_service

    return build_research_application_service()


def _report_service_factory():
    from interfaces.services.report_service import ReportApplicationService

    return ReportApplicationService()


def _source_service_factory():
    from interfaces.services.source_service import SourceApplicationService

    return SourceApplicationService()


def _entity_service_factory():
    from interfaces.services.entity_service import EntityTrackingApplicationService

    return EntityTrackingApplicationService()


def _subscription_service_factory():
    from interfaces.services.subscription_service import SubscriptionApplicationService

    return SubscriptionApplicationService()


def _memory_service_factory():
    from interfaces.services.memory_service import MemoryApplicationService

    return MemoryApplicationService()


def _diagnostic_service_factory():
    from interfaces.services.diagnose_service import DiagnosticApplicationService

    return DiagnosticApplicationService()


def _approval_service_factory():
    from interfaces.services.approval_service import ApprovalApplicationService

    return ApprovalApplicationService()


def _graph_run_inspection_service_factory():
    from interfaces.services.run_inspection_factory import (
        graph_run_inspection_service_from_env,
    )

    return graph_run_inspection_service_from_env()


def _graph_run_operation_service_factory():
    from interfaces.services.run_operation_service import GraphRunOperationApplicationService

    return GraphRunOperationApplicationService()


def _artifact_service_factory():
    from interfaces.services.artifact_service import ArtifactInspectionService

    return ArtifactInspectionService()


def _storage_service_factory():
    from interfaces.services.storage_service import StorageApplicationService

    return StorageApplicationService()


def _event_operator_service_factory(actor: ActorContext):
    from interfaces.services.event_operator_factory import (
        event_operator_service_from_actor,
    )

    return event_operator_service_from_actor(actor)


def _deployment_event_operator_actor() -> ActorContext | None:
    principal_id = str(
        os.environ.get("NEWS_EVENT_OPERATOR_PRINCIPAL_ID") or ""
    ).strip()
    tenant_id = str(os.environ.get("NEWS_TENANT_ID") or "").strip()
    if not principal_id or not tenant_id:
        return None
    role = str(os.environ.get("NEWS_EVENT_OPERATOR_ROLE") or "operator").strip()
    if role not in {"admin", "operator", "service"}:
        return None
    return ActorContext(
        actor_id=principal_id,
        actor_type="service",
        roles=[role],
        request_id="mcp-stdio",
        metadata={"tenant_id": tenant_id},
    )


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


def _run_events_resource_args(uri: str) -> dict[str, Any] | None:
    parsed = urlsplit(uri)
    if parsed.scheme != "news" or parsed.netloc != "runs":
        return None
    parts = [unquote(part) for part in parsed.path.strip("/").split("/") if part]
    if len(parts) != 2 or parts[1] != "events":
        return None
    args = {
        key: values[-1]
        for key, values in parse_qs(parsed.query, keep_blank_values=True).items()
        if values
    }
    args["run_id"] = parts[0]
    return args


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


def _artifact_resource_ids(uri: str) -> tuple[str, str] | None:
    parsed = urlsplit(uri)
    if parsed.scheme != "news" or parsed.netloc != "artifacts":
        return None
    artifact_id = unquote(parsed.path.strip("/"))
    if not artifact_id:
        return None
    query = parse_qs(parsed.query)
    run_id = (query.get("run_id") or [None])[-1]
    if run_id:
        return str(run_id), artifact_id
    if ":" not in artifact_id:
        return None
    resolved_run_id, artifact_key = artifact_id.split(":", 1)
    if not resolved_run_id or not artifact_key:
        return None
    return resolved_run_id, artifact_key


def _memory_resource_args(uri: str) -> dict[str, Any] | None:
    parsed = urlsplit(uri)
    if parsed.scheme != "news" or parsed.netloc != "memory":
        return None
    document_id = unquote(parsed.path.strip("/"))
    if not document_id:
        return None
    args = {key: values[-1] for key, values in parse_qs(parsed.query).items() if values}
    args["document_id"] = document_id
    return args


def _storage_retention_plan_resource_args(uri: str) -> dict[str, Any] | None:
    parsed = urlsplit(uri)
    base_uri = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    if base_uri != STORAGE_RETENTION_PLAN_RESOURCE_URI:
        return None
    return {key: values[-1] for key, values in parse_qs(parsed.query).items() if values}


def _worker_status_resource_args(uri: str) -> dict[str, Any] | None:
    parsed = urlsplit(uri)
    if parsed.scheme != "news" or parsed.netloc != "workers":
        return None
    worker_id = parsed.path.strip("/")
    if "/" in worker_id:
        return None
    args = {key: values[-1] for key, values in parse_qs(parsed.query).items() if values}
    if worker_id:
        args["worker_id"] = unquote(worker_id)
    return args


def _queue_status_resource_args(uri: str) -> dict[str, Any] | None:
    parsed = urlsplit(uri)
    if parsed.scheme != "news" or parsed.netloc != "queues" or parsed.path:
        return None
    query = parse_qs(parsed.query)
    return {"queue_names": [value for value in query.get("queue_name", []) if value]}


def _event_operator_resource_args(
    uri: str,
) -> tuple[str, dict[str, Any]] | None:
    parsed = urlsplit(uri)
    if not is_event_operator_resource_uri(uri):
        return None
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    query = parse_qs(parsed.query, keep_blank_values=False)
    if parts == ["quarantine"]:
        _require_query_keys(query, {"reason", "disposition", "cursor", "limit"})
        return (
            "quarantine_list",
            {
                "reason": _query_value(query, "reason"),
                "disposition": _query_value(query, "disposition"),
                "cursor": _query_value(query, "cursor"),
                "limit": _query_int(query, "limit", default=100),
            },
        )
    if len(parts) == 2 and parts[0] == "quarantine":
        _require_query_keys(query, set())
        return "quarantine_get", {"quarantine_id": parts[1]}
    if parts == ["replay-reports"]:
        _require_query_keys(
            query,
            {"source_stream_id", "mode", "status", "cursor", "limit"},
        )
        return (
            "replay_report_list",
            {
                "source_stream_id": _query_value(query, "source_stream_id"),
                "mode": _query_value(query, "mode"),
                "status": _query_value(query, "status"),
                "cursor": _query_value(query, "cursor"),
                "limit": _query_int(query, "limit", default=100),
            },
        )
    if len(parts) == 2 and parts[0] == "replay-reports":
        _require_query_keys(query, set())
        return "replay_report_get", {"replay_id": parts[1]}
    if parts == ["dead-letters"]:
        _require_query_keys(
            query,
            {
                "subscription_id",
                "subscription_version",
                "disposition",
                "cursor",
                "limit",
            },
        )
        version = _query_value(query, "subscription_version")
        return (
            "dead_letter_list",
            {
                "subscription_id": _query_value(query, "subscription_id"),
                "subscription_version": None if version is None else int(version),
                "disposition": _query_value(query, "disposition"),
                "cursor": _query_value(query, "cursor"),
                "limit": _query_int(query, "limit", default=100),
            },
        )
    if len(parts) == 2 and parts[0] == "dead-letters":
        _require_query_keys(query, set())
        return "dead_letter_get", {"dead_letter_id": parts[1]}
    if (
        len(parts) == 6
        and parts[0] == "consumers"
        and parts[2] == "versions"
        and parts[4] == "status"
    ):
        # Reserved for a future URI shape with a stream path segment.
        return None
    if (
        len(parts) == 5
        and parts[0] == "consumers"
        and parts[2] == "versions"
        and parts[4] == "status"
    ):
        _require_query_keys(query, {"stream_id"})
        stream_id = _query_value(query, "stream_id")
        if stream_id is None:
            raise ValueError("stream_id query parameter is required")
        return (
            "consumer_status",
            {
                "subscription_id": parts[1],
                "subscription_version": int(parts[3]),
                "stream_id": stream_id,
            },
        )
    if (
        len(parts) == 4
        and parts[0] == "projections"
        and parts[1] == "runs"
        and parts[3] == "status"
    ):
        _require_query_keys(query, set())
        return "projection_status", {"run_id": parts[2]}
    return None


def _query_value(query: dict[str, list[str]], name: str) -> str | None:
    values = query.get(name, [])
    if len(values) > 1:
        raise ValueError(f"{name} query parameter must be singular")
    return values[0] if values else None


def _query_int(query: dict[str, list[str]], name: str, *, default: int) -> int:
    value = _query_value(query, name)
    return default if value is None else int(value)


def _require_query_keys(
    query: dict[str, list[str]],
    allowed: set[str],
) -> None:
    unexpected = sorted(set(query).difference(allowed))
    if unexpected:
        raise ValueError(f"unsupported event resource query parameter: {unexpected[0]}")


def _require_event_operator_confirmation(args: dict[str, Any]) -> None:
    if args.get("confirm") is not True:
        raise ValueError("event operator mutation requires confirm=true")


def _validate_event_operator_tool_args(
    tool_name: str,
    args: dict[str, Any],
) -> None:
    allowed_by_tool = {
        "news.event.quarantine.list": {
            "reason",
            "disposition",
            "cursor",
            "limit",
        },
        "news.event.quarantine.get": {"quarantine_id"},
        "news.event.replay_reports.list": {
            "source_stream_id",
            "mode",
            "status",
            "cursor",
            "limit",
        },
        "news.event.replay_reports.get": {"replay_id"},
        "news.event.dead_letters.list": {
            "subscription_id",
            "subscription_version",
            "disposition",
            "cursor",
            "limit",
        },
        "news.event.dead_letters.get": {"dead_letter_id"},
        "news.event.dead_letters.resolve": {
            "dead_letter_id",
            "operator_reason",
            "confirm",
        },
        "news.event.dead_letters.requeue": {
            "dead_letter_id",
            "subscription_id",
            "subscription_version",
            "operator_reason",
            "confirm",
        },
        "news.event.consumer_status": {
            "subscription_id",
            "subscription_version",
            "stream_id",
        },
        "news.event.projection_status": {"run_id"},
    }
    allowed = allowed_by_tool.get(tool_name)
    if allowed is None:
        return
    unexpected = sorted(set(args).difference(allowed))
    if unexpected:
        raise ValueError(f"unsupported event operator argument: {unexpected[0]}")


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


def _optional_arg(args: dict[str, Any], name: str) -> str | None:
    value = args.get(name)
    if value is None or value == "":
        return None
    return str(value)


def _research_actor_input(
    args: dict[str, Any],
    actor: ActorContext | None,
) -> ResearchActorInput:
    return bind_research_actor_input(
        ResearchActorInput(
            tenant_id=_optional_arg(args, "tenant_id"),
            user_id=_optional_arg(args, "user_id"),
            memory_namespace=_optional_arg(args, "memory_namespace"),
        ),
        actor,
    )


def _optional_int_arg(args: dict[str, Any], name: str, *, default: int) -> int:
    value = args.get(name)
    if value is None or value == "":
        return default
    return int(value)


def _optional_bool_arg(args: dict[str, Any], name: str, *, default: bool) -> bool:
    value = args.get(name)
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return bool(value)


def _optional_text_tuple(args: dict[str, Any], name: str) -> tuple[str, ...] | None:
    value = args.get(name)
    if value is None:
        return None
    if isinstance(value, str):
        items = (value,)
    elif isinstance(value, (list, tuple)):
        items = tuple(str(item) for item in value)
    else:
        raise ValueError(f"{name} must be a string list")
    normalized = tuple(item.strip() for item in items if item.strip())
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def _string_list_arg(args: dict[str, Any], name: str) -> list[str]:
    value = args.get(name)
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return [str(value)]


def _queue_names_from_args(args: dict[str, Any]) -> list[str] | None:
    value = args.get("queue_names", args.get("queue_name"))
    if value is None or value == "":
        return None
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return [str(value)]


def _retention_policy_from_args(args: dict[str, Any]) -> RetentionPolicy | None:
    values = {
        name: int(args[name])
        for name in RETENTION_POLICY_ARG_NAMES
        if name in args and args[name] is not None and args[name] != ""
    }
    if not values:
        return None
    return RetentionPolicy.from_dict(values)


def _optional_datetime_arg(args: dict[str, Any], name: str) -> datetime | None:
    value = args.get(name)
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _decided_by(args: dict[str, Any]) -> str:
    decided_by = str(args.get("decided_by") or "")
    if not decided_by:
        raise ValueError("decided_by is required")
    return decided_by
