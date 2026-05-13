from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlsplit

from interfaces.mcp.models import (
    MCPCatalog,
    MCPPrompt,
    MCPPromptGetResult,
    MCPResource,
    MCPResourceReadResult,
    MCPTool,
    MCPToolCallResult,
)
from storage.lifecycle import RetentionPolicy


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
RETENTION_POLICY_ARG_NAMES = (
    "raw_source_retention_days",
    "llm_artifact_retention_days",
    "run_artifact_retention_days",
    "report_retention_days",
    "evidence_retention_days",
    "vector_retention_days",
)


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
        run_inspection_service_factory: Callable[[], Any] | None = None,
        artifact_service_factory: Callable[[], Any] | None = None,
        storage_service_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.worker_service_factory = worker_service_factory or _worker_service_factory
        self.run_service_factory = run_service_factory or _run_service_factory
        self.report_service_factory = report_service_factory or _report_service_factory
        self.source_service_factory = source_service_factory or _source_service_factory
        self.entity_service_factory = entity_service_factory or _entity_service_factory
        self.subscription_service_factory = (
            subscription_service_factory or _subscription_service_factory
        )
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
            return MCPResourceReadResult(
                uri=uri,
                success=False,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

    def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> MCPToolCallResult:
        args = arguments or {}
        try:
            if tool_name == "news.daily.run":
                return self._daily_run(args)
            if tool_name == "news.topic.run":
                return self._topic_run(args)
            if tool_name == "news.weekly.run":
                return self._weekly_run(args)
            if tool_name == "news.daily.enqueue":
                return self._daily_enqueue(args)
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
            if tool_name == "news.memory.search":
                return self._memory_search(args)
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

    def _daily_run(self, args: dict[str, Any]) -> MCPToolCallResult:
        result = self.run_service_factory().run_daily(
            profile=str(args.get("profile") or "live-offline"),
            topic=str(args.get("topic") or "AI"),
            source_limit=_optional_int_arg(args, "source_limit", default=3),
            run_id=_optional_arg(args, "run_id"),
        )
        return MCPToolCallResult(
            tool_name="news.daily.run",
            success=True,
            data=result.to_dict(),
        )

    def _topic_run(self, args: dict[str, Any]) -> MCPToolCallResult:
        result = self.run_service_factory().run_daily(
            profile=str(args.get("profile") or "live-offline"),
            topic=_required_arg(args, "topic"),
            source_limit=_optional_int_arg(args, "source_limit", default=3),
            run_id=_optional_arg(args, "run_id"),
        )
        return MCPToolCallResult(
            tool_name="news.topic.run",
            success=True,
            data=result.to_dict(),
        )

    def _weekly_run(self, args: dict[str, Any]) -> MCPToolCallResult:
        result = self.run_service_factory().run_weekly(
            language=str(args.get("language") or "en"),
            topic=_optional_arg(args, "topic"),
            source_limit=_optional_int_arg(args, "source_limit", default=20),
            period_start=_optional_arg(args, "period_start"),
            period_end=_optional_arg(args, "period_end"),
            run_id=_optional_arg(args, "run_id"),
        )
        return MCPToolCallResult(
            tool_name="news.weekly.run",
            success=True,
            data=result.to_dict(),
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

    def _report_list(self, args: dict[str, Any]) -> MCPToolCallResult:
        result = self.report_service_factory().list_reports(
            limit=_optional_int_arg(args, "limit", default=20),
            workflow_id=_optional_arg(args, "workflow_id"),
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
            workflow_id=_optional_arg(args, "workflow_id"),
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
            data=subscription.to_dict(),
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

    def _run_diagnostics(self, args: dict[str, Any]) -> MCPToolCallResult:
        run_id = str(args.get("run_id") or "")
        if not run_id:
            raise ValueError("run_id is required")
        result = self.run_inspection_service_factory().get_run_diagnostics(run_id)
        return MCPToolCallResult(
            tool_name="news.run.diagnostics",
            success=True,
            data=result.to_dict(),
        )

    def _run_health(self, args: dict[str, Any]) -> MCPToolCallResult:
        run_id = str(args.get("run_id") or "")
        if not run_id:
            raise ValueError("run_id is required")
        result = self.run_inspection_service_factory().get_run_health(run_id)
        return MCPToolCallResult(
            tool_name="news.run.health",
            success=True,
            data=result.to_dict(),
        )

    def _run_catalog_health(self) -> MCPToolCallResult:
        result = self.run_inspection_service_factory().get_catalog_health()
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
        result = self.run_inspection_service_factory().compare_runs(
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
            name="news.daily.run",
            title="Run daily intelligence",
            description="Run daily intelligence directly through RunApplicationService.",
            input_schema={
                "type": "object",
                "properties": {
                    "profile": {"type": "string", "enum": ["live", "live-offline"]},
                    "topic": {"type": "string"},
                    "source_limit": {"type": "integer", "minimum": 1},
                    "run_id": {"type": "string"},
                },
            },
        ),
        MCPTool(
            name="news.topic.run",
            title="Run topic intelligence",
            description="Run a topic-focused daily intelligence workflow through RunApplicationService.",
            input_schema={
                "type": "object",
                "required": ["topic"],
                "properties": {
                    "profile": {"type": "string", "enum": ["live", "live-offline"]},
                    "topic": {"type": "string"},
                    "source_limit": {"type": "integer", "minimum": 1},
                    "run_id": {"type": "string"},
                },
            },
        ),
        MCPTool(
            name="news.weekly.run",
            title="Run weekly intelligence",
            description="Run weekly intelligence directly through RunApplicationService.",
            input_schema={
                "type": "object",
                "properties": {
                    "language": {"type": "string", "enum": ["en"]},
                    "topic": {"type": "string"},
                    "source_limit": {"type": "integer", "minimum": 1},
                    "period_start": {"type": "string", "format": "date-time"},
                    "period_end": {"type": "string", "format": "date-time"},
                    "run_id": {"type": "string"},
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
                    "workflow_id": {"type": "string"},
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
                    "workflow_id": {"type": "string"},
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
                    "profile": {"type": "string", "enum": ["live", "live-offline"]},
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
            name="news.run.diagnostics",
            title="Inspect run diagnostics",
            description="Read workflow run diagnostics through RunInspectionService.",
            input_schema={
                "type": "object",
                "required": ["run_id"],
                "properties": {"run_id": {"type": "string"}},
            },
        ),
        MCPTool(
            name="news.run.health",
            title="Inspect run health",
            description="Read workflow run health through RunInspectionService.",
            input_schema={
                "type": "object",
                "required": ["run_id"],
                "properties": {"run_id": {"type": "string"}},
            },
        ),
        MCPTool(
            name="news.run.catalog_health",
            title="Inspect run catalog health",
            description="Read workflow run catalog health through RunInspectionService.",
            input_schema={"type": "object", "properties": {}},
        ),
        MCPTool(
            name="news.run.compare",
            title="Compare workflow runs",
            description="Compare two workflow runs through RunInspectionService.",
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
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return dict(value)
    raise TypeError(f"value is not JSON-safe: {type(value).__name__}")


def _worker_service_factory():
    from interfaces.services.worker_service import WorkerApplicationService

    return WorkerApplicationService()


def _run_service_factory():
    from interfaces.services.run_service import RunApplicationService

    return RunApplicationService()


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
