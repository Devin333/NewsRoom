from __future__ import annotations

import hmac
import json
import os
import re
from collections.abc import Mapping, Sequence
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.framework.tools.redaction import redact_sensitive_values
from core.framework.workers.approval import ApprovalAlreadyDecidedError, ApprovalNotFoundError
from core.framework.workers.schedule_store import ScheduleNotFoundError, ScheduleRecord
from core.framework.workers.scheduler import ScheduleSpec
from interfaces.models import (
    ActorContext,
    ApiError,
    ApiResponse,
    ApprovalDecisionRequest,
    ApprovalModifyRequest,
    ArxivSourceFetchRequest,
    ArtifactRef,
    ApprovalSubmitRequest,
    DailyRunRequest,
    EntityCreateRequest,
    GithubReleaseFetchRequest,
    DailyScheduleRequest,
    ManualScheduleTriggerRequest,
    MemorySearchRequest,
    MemoryReindexRequest,
    ReportActionRequest,
    ReportDetail,
    RunRequest,
    RunResponse,
    ScheduleTickRequest,
    SourceProbeRequest,
    TopicSubscriptionCreateRequest,
    WeeklyRunRequest,
    actor_context_from_headers,
)
from interfaces.api.rate_limit import Clock, InMemoryRateLimiter
from interfaces.events import AuditEmitter, audit_emitter_from_env
from interfaces.services.approval_service import ApprovalApplicationService
from interfaces.services.diagnose_service import DiagnosticApplicationService
from interfaces.services.entity_service import EntityTrackingApplicationService
from interfaces.services.memory_service import MemoryApplicationService
from interfaces.services.mcp_service import MCPApplicationService
from interfaces.services.report_service import ReportApplicationService
from interfaces.services.run_inspection_service import RunInspectionService
from interfaces.services.run_service import RunApplicationService
from interfaces.services.schedule_service import ScheduleApplicationService
from interfaces.services.source_service import SourceApplicationService
from interfaces.services.storage_service import StorageApplicationService
from interfaces.services.subscription_service import SubscriptionApplicationService
from interfaces.services.worker_service import WorkerApplicationService
from interfaces.services.artifact_service import ArtifactInspectionService
from storage.lifecycle import RetentionPolicy


WorkerServiceFactory = Callable[[], WorkerApplicationService]
RunServiceFactory = Callable[[], RunApplicationService]
ReportServiceFactory = Callable[[], ReportApplicationService]
MemoryServiceFactory = Callable[[], MemoryApplicationService]
DiagnosticServiceFactory = Callable[[], DiagnosticApplicationService]
SourceServiceFactory = Callable[[], SourceApplicationService]
EntityServiceFactory = Callable[[], EntityTrackingApplicationService]
SubscriptionServiceFactory = Callable[[], SubscriptionApplicationService]
MCPServiceFactory = Callable[[], MCPApplicationService]
RunInspectionServiceFactory = Callable[[], RunInspectionService]
ArtifactInspectionServiceFactory = Callable[[], ArtifactInspectionService]
StorageServiceFactory = Callable[[], StorageApplicationService]
ScheduleServiceFactory = Callable[[], ScheduleApplicationService]
ApprovalServiceFactory = Callable[[], ApprovalApplicationService]
AuditEmitterFactory = Callable[[], AuditEmitter | None]
ApiKeyRoles = Mapping[str, str | Sequence[str]]
REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_CONTEXT: ContextVar[str | None] = ContextVar("news_api_request_id", default=None)
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def create_app(
    *,
    worker_service_factory: WorkerServiceFactory = WorkerApplicationService,
    run_service_factory: RunServiceFactory = RunApplicationService,
    report_service_factory: ReportServiceFactory = ReportApplicationService,
    memory_service_factory: MemoryServiceFactory = MemoryApplicationService,
    diagnostic_service_factory: DiagnosticServiceFactory = DiagnosticApplicationService,
    source_service_factory: SourceServiceFactory = SourceApplicationService,
    entity_service_factory: EntityServiceFactory = EntityTrackingApplicationService,
    subscription_service_factory: SubscriptionServiceFactory = SubscriptionApplicationService,
    mcp_service_factory: MCPServiceFactory = MCPApplicationService,
    run_inspection_service_factory: RunInspectionServiceFactory = RunInspectionService,
    artifact_service_factory: ArtifactInspectionServiceFactory = ArtifactInspectionService,
    storage_service_factory: StorageServiceFactory = StorageApplicationService,
    schedule_service_factory: ScheduleServiceFactory = ScheduleApplicationService,
    approval_service_factory: ApprovalServiceFactory = ApprovalApplicationService,
    audit_emitter_factory: AuditEmitterFactory | None = audit_emitter_from_env,
    api_token: str | None = None,
    api_keys: ApiKeyRoles | None = None,
    api_rate_limit_per_minute: int | None = None,
    rate_limit_clock: Clock | None = None,
) -> FastAPI:
    api = FastAPI(title="NewsRoom API", version="0.1.0")
    resolved_api_keys = _build_api_key_registry(api_token=api_token, api_keys=api_keys)
    rate_limiter = _build_rate_limiter(api_rate_limit_per_minute, clock=rate_limit_clock)
    audit_emitter = audit_emitter_factory() if audit_emitter_factory else None

    if rate_limiter is not None:

        @api.middleware("http")
        async def rate_limit_middleware(request: Request, call_next):
            if _requires_api_auth(request.url.path):
                decision = rate_limiter.check(_client_rate_limit_key(request))
                if not decision.allowed:
                    return _error(
                        status_code=429,
                        code="rate_limited",
                        message="API rate limit exceeded",
                        details={
                            "limit": decision.limit,
                            "window_seconds": rate_limiter.window_seconds,
                            "remaining": decision.remaining,
                        },
                        retryable=True,
                        headers={"Retry-After": str(decision.retry_after_seconds)},
                    )
            return await call_next(request)

    if resolved_api_keys:

        @api.middleware("http")
        async def bearer_token_rbac(request: Request, call_next):
            if not _requires_api_auth(request.url.path):
                return await call_next(request)
            actor = _authorized_api_actor(request, resolved_api_keys)
            if actor is None:
                return _error(
                    status_code=401,
                    code="unauthorized",
                    message="valid bearer token required",
                    user_action_required=True,
                    headers={"WWW-Authenticate": "Bearer"},
                )
            request.state.actor_context = actor
            required_permission = _required_api_permission(request.method, request.url.path)
            if required_permission and not actor.has_permission(required_permission):
                return _error(
                    status_code=403,
                    code="forbidden",
                    message=f"missing required permission: {required_permission}",
                    details={
                        "required_permission": required_permission,
                        "roles": actor.roles,
                    },
                    user_action_required=True,
                )
            return await call_next(request)

    @api.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = _request_id_from_header(request.headers.get(REQUEST_ID_HEADER)) or _new_request_id()
        context_token = _REQUEST_ID_CONTEXT.set(request_id)
        try:
            response = await call_next(request)
        finally:
            _REQUEST_ID_CONTEXT.reset(context_token)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

    @api.middleware("http")
    async def audit_middleware(request: Request, call_next):
        try:
            response = await call_next(request)
        except Exception:
            _emit_api_audit(
                audit_emitter,
                request,
                request_id=_request_id_from_header(request.headers.get(REQUEST_ID_HEADER))
                or _request_id(),
                status_code=500,
                result="failed",
            )
            raise
        request_id = response.headers.get(REQUEST_ID_HEADER) or _request_id()
        _emit_api_audit(
            audit_emitter,
            request,
            request_id=request_id,
            status_code=response.status_code,
            result=_audit_result(response.status_code),
        )
        return response

    @api.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return _error(
            status_code=422,
            code="invalid_request",
            message="request validation failed",
            details=_validation_error_details(exc.errors()),
            user_action_required=True,
        )

    @api.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        return _error(
            status_code=exc.status_code,
            code=_http_error_code(exc.status_code),
            message=str(exc.detail or "HTTP error"),
            headers=exc.headers,
        )

    @api.get("/health")
    def health() -> dict:
        return _success({"status": "ok", "service": "newsroom-api"})

    @api.get("/health/live")
    def live_health() -> dict:
        return _success({"status": "ok", "service": "newsroom-api", "live": True})

    @api.get("/health/ready")
    def ready_health() -> dict:
        return _success({"status": "ok", "service": "newsroom-api", "ready": True})

    @api.get("/health/dependencies")
    def dependency_health() -> dict:
        return _success(diagnostic_service_factory().run().to_dict())

    @api.post("/api/v1/runs")
    def submit_run(request: RunRequest):
        workflow_id = request.workflow_id.strip().lower()
        try:
            if workflow_id in {"daily", "daily-intelligence", "daily_intelligence"}:
                source_limit = request.source_limit or request.max_items or 3
                if request.async_run:
                    result = worker_service_factory().enqueue_daily(
                        profile=request.profile,
                        topic=request.topic or "AI",
                        source_limit=source_limit,
                        run_id=request.run_id,
                        queue_name=request.queue_name,
                    )
                    data = RunResponse(
                        run_id=request.run_id,
                        task_id=result.task.task_id,
                        status="queued",
                        task_status=result.task.status.value,
                        message=f"queued as {result.message_id}",
                    )
                    return _success(_model_to_dict(data))
                result = run_service_factory().run_daily(
                    profile=request.profile,
                    topic=request.topic or "AI",
                    source_limit=source_limit,
                    run_id=request.run_id,
                )
                return _success(_run_result_response(result))
            if workflow_id in {"weekly", "weekly-intelligence", "weekly_intelligence"}:
                result = run_service_factory().run_weekly(
                    language=request.language,
                    topic=request.topic,
                    source_limit=request.source_limit or request.max_items or 20,
                    run_id=request.run_id,
                )
                return _success(_run_result_response(result))
        except ValueError as exc:
            return _error(status_code=400, code="invalid_run_request", message=str(exc))
        return _error(
            status_code=404,
            code="workflow_not_found",
            message=f"unknown workflow_id: {request.workflow_id}",
            user_action_required=True,
        )

    @api.post("/api/v1/runs/daily")
    def submit_daily_run(request: DailyRunRequest):
        result = worker_service_factory().enqueue_daily(
            profile=request.profile,
            topic=request.topic,
            source_limit=request.source_limit,
            run_id=request.run_id,
            queue_name=request.queue_name,
        )
        data = RunResponse(
            run_id=request.run_id,
            task_id=result.task.task_id,
            status="queued",
            task_status=result.task.status.value,
            message=f"queued as {result.message_id}",
        )
        return _success(_model_to_dict(data))

    @api.post("/api/v1/runs/weekly")
    def run_weekly(request: WeeklyRunRequest):
        try:
            result = run_service_factory().run_weekly(
                language=request.language,
                topic=request.topic,
                source_limit=request.source_limit,
                period_start=request.period_start,
                period_end=request.period_end,
                run_id=request.run_id,
            )
        except ValueError as exc:
            return _error(status_code=400, code="invalid_weekly_run_request", message=str(exc))
        return _success(_run_result_response(result))

    @api.get("/api/v1/workers")
    def list_workers(stale_after_seconds: int = 60):
        try:
            result = worker_service_factory().list_worker_status(
                stale_after_seconds=stale_after_seconds
            )
        except ValueError as exc:
            return _error(status_code=400, code="invalid_worker_status_request", message=str(exc))
        return _success(result.to_dict())

    @api.get("/api/v1/workers/{worker_id}")
    def get_worker(worker_id: str, stale_after_seconds: int = 60):
        try:
            result = worker_service_factory().list_worker_status(
                worker_id=worker_id,
                stale_after_seconds=stale_after_seconds,
            )
        except ValueError as exc:
            return _error(status_code=400, code="invalid_worker_status_request", message=str(exc))
        return _success(result.to_dict())

    @api.get("/api/v1/queues")
    def list_queues(queue_name: list[str] | None = Query(default=None)):
        result = worker_service_factory().queue_status(queue_names=queue_name)
        return _success(result.to_dict())

    @api.get("/api/v1/reports/latest")
    def latest_report():
        try:
            record = report_service_factory().latest_report()
        except FileNotFoundError as exc:
            return _error(
                status_code=404,
                code="report_not_found",
                message=str(exc),
                user_action_required=True,
            )
        data = ReportDetail(
            report_id=record.report_id,
            run_id=record.run_id,
            status=record.status,
            title=record.title,
            report_json=record.report_json,
            report_markdown=record.report_markdown,
            quality_score=record.quality_score,
            manifest_path=_optional_str(record.manifest_path),
        )
        return _success(_model_to_dict(data))

    @api.get("/api/v1/reports")
    def list_reports(limit: int = 20, workflow_id: str | None = None):
        try:
            result = report_service_factory().list_reports(
                limit=limit,
                workflow_id=workflow_id,
            )
        except ValueError as exc:
            return _error(status_code=400, code="invalid_report_catalog", message=str(exc))
        return _success(result.to_dict())

    @api.get("/api/v1/reports/{report_id}")
    def get_report(report_id: str):
        try:
            record = report_service_factory().get_report(report_id)
        except FileNotFoundError as exc:
            return _error(
                status_code=404,
                code="report_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except ValueError as exc:
            return _error(status_code=400, code="invalid_report_id", message=str(exc))
        data = ReportDetail(
            report_id=record.report_id,
            run_id=record.run_id,
            status=record.status,
            title=record.title,
            report_json=record.report_json,
            report_markdown=record.report_markdown,
            quality_score=record.quality_score,
            manifest_path=_optional_str(record.manifest_path),
        )
        return _success(_model_to_dict(data))

    @api.get("/api/v1/reports/{report_id}/markdown")
    def get_report_markdown(report_id: str):
        try:
            result = report_service_factory().report_markdown(report_id)
        except FileNotFoundError as exc:
            return _error(
                status_code=404,
                code="report_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except ValueError as exc:
            return _error(status_code=400, code="invalid_report_id", message=str(exc))
        return _success(result.to_dict())

    @api.get("/api/v1/reports/{report_id}/quality")
    def get_report_quality(report_id: str):
        try:
            result = report_service_factory().report_quality(report_id)
        except FileNotFoundError as exc:
            return _error(
                status_code=404,
                code="report_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except ValueError as exc:
            return _error(status_code=400, code="invalid_report_id", message=str(exc))
        return _success(result.to_dict())

    @api.post("/api/v1/reports/{report_id}/request-review")
    def request_report_review(report_id: str, request: ReportActionRequest | None = None):
        actual_request = request or ReportActionRequest()
        try:
            action = report_service_factory().request_review(
                report_id,
                requested_by=actual_request.requested_by,
                reason=actual_request.reason,
                metadata=actual_request.metadata,
            )
            approval = approval_service_factory().submit_request(
                requested_action="review_report",
                risk_level="low",
                reason=actual_request.reason,
                payload={"report_id": report_id, **actual_request.metadata},
                requested_by=actual_request.requested_by,
            )
        except FileNotFoundError as exc:
            return _error(status_code=404, code="report_not_found", message=str(exc))
        except ValueError as exc:
            return _error(status_code=400, code="invalid_report_action", message=str(exc))
        data = action.to_dict()
        data["approval"] = approval.to_dict()
        return _success(data)

    @api.post("/api/v1/reports/{report_id}/publish")
    def publish_report(report_id: str, request: ReportActionRequest | None = None):
        actual_request = request or ReportActionRequest()
        try:
            action = report_service_factory().publish_report(
                report_id,
                requested_by=actual_request.requested_by,
                reason=actual_request.reason,
                metadata=actual_request.metadata,
            )
            approval = approval_service_factory().submit_request(
                requested_action="publish_report",
                risk_level="high",
                reason=actual_request.reason,
                payload={"report_id": report_id, **actual_request.metadata},
                requested_by=actual_request.requested_by,
            )
        except FileNotFoundError as exc:
            return _error(status_code=404, code="report_not_found", message=str(exc))
        except ValueError as exc:
            return _error(status_code=400, code="invalid_report_action", message=str(exc))
        data = action.to_dict()
        data["approval"] = approval.to_dict()
        return _success(data)

    @api.get("/api/v1/search/reports")
    def search_reports(q: str, limit: int = 20):
        try:
            result = report_service_factory().search_reports(query=q, limit=limit)
        except ValueError as exc:
            return _error(status_code=400, code="invalid_report_search", message=str(exc))
        return _success(result.to_dict())

    @api.post("/api/v1/memory/search")
    def memory_search(request: MemorySearchRequest):
        result = memory_service_factory().search(
            text=request.query,
            collection=request.collection,
            limit=request.limit,
            filters=request.filters,
        )
        return _success(result.to_dict())

    @api.post("/api/v1/memory/reindex")
    def memory_reindex(request: MemoryReindexRequest):
        try:
            result = memory_service_factory().reindex_run(request.run_id, topic=request.topic)
        except FileNotFoundError as exc:
            return _error(
                status_code=404,
                code="memory_reindex_source_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except ValueError as exc:
            return _error(status_code=400, code="invalid_memory_reindex_request", message=str(exc))
        return _success(result.to_dict())

    @api.get("/api/v1/memory/{document_id}")
    def memory_document(document_id: str, collection: str = "report_sections"):
        try:
            result = memory_service_factory().get_document(document_id, collection=collection)
        except FileNotFoundError as exc:
            return _error(
                status_code=404,
                code="memory_document_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except ValueError as exc:
            return _error(status_code=400, code="invalid_memory_document_request", message=str(exc))
        return _success(result.to_dict())

    @api.get("/api/v1/admin/diagnose")
    def diagnose():
        return _success(diagnostic_service_factory().run().to_dict())

    @api.get("/api/v1/storage/metrics")
    def storage_metrics():
        return _success(storage_service_factory().metrics().to_dict())

    @api.get("/api/v1/storage/retention/plan")
    def storage_retention_plan(
        run_id: str | None = None,
        now: datetime | None = None,
        raw_source_retention_days: int | None = None,
        llm_artifact_retention_days: int | None = None,
        run_artifact_retention_days: int | None = None,
        report_retention_days: int | None = None,
        evidence_retention_days: int | None = None,
        vector_retention_days: int | None = None,
    ):
        try:
            policy = RetentionPolicy.from_dict(
                _provided_values(
                    raw_source_retention_days=raw_source_retention_days,
                    llm_artifact_retention_days=llm_artifact_retention_days,
                    run_artifact_retention_days=run_artifact_retention_days,
                    report_retention_days=report_retention_days,
                    evidence_retention_days=evidence_retention_days,
                    vector_retention_days=vector_retention_days,
                )
            )
            result = storage_service_factory().plan_retention(
                policy=policy,
                run_id=run_id,
                now=now,
            )
        except ValueError as exc:
            return _error(
                status_code=400,
                code="invalid_storage_retention_request",
                message=str(exc),
            )
        return _success(result.to_dict())

    @api.get("/api/v1/sources")
    def list_sources(include_disabled: bool = False):
        return _success(source_service_factory().list_sources(enabled_only=not include_disabled).to_dict())

    @api.get("/api/v1/sources/health")
    def source_health(include_disabled: bool = False):
        return _success(source_service_factory().source_health(enabled_only=not include_disabled).to_dict())

    @api.get("/api/v1/sources/validation")
    def validate_sources():
        return _success(source_service_factory().validate_sources().to_dict())

    @api.get("/api/v1/sources/{source_id}")
    def get_source(source_id: str):
        try:
            result = source_service_factory().get_source(source_id)
        except KeyError as exc:
            return _error(
                status_code=404,
                code="source_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except ValueError as exc:
            return _error(status_code=400, code="invalid_source_request", message=str(exc))
        return _success(result.to_dict())

    @api.post("/api/v1/sources/{source_id}/probe")
    def probe_source(source_id: str, request: SourceProbeRequest | None = None):
        actual_request = request or SourceProbeRequest()
        try:
            result = source_service_factory().check_source_health(
                source_id=source_id,
                enabled_only=not actual_request.include_disabled,
                limit=actual_request.limit,
                force=actual_request.force,
            )
        except KeyError as exc:
            return _error(
                status_code=404,
                code="source_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except ValueError as exc:
            return _error(status_code=400, code="invalid_source_probe", message=str(exc))
        return _success(result.to_dict())

    @api.post("/api/v1/sources/arxiv/fetch")
    def fetch_arxiv_source(request: ArxivSourceFetchRequest):
        try:
            result = source_service_factory().fetch_arxiv(query=request.query, limit=request.limit)
        except ValueError as exc:
            return _error(status_code=400, code="invalid_arxiv_source_request", message=str(exc))
        return _success(result.to_dict())

    @api.post("/api/v1/sources/github/releases")
    def fetch_github_releases(request: GithubReleaseFetchRequest):
        try:
            result = source_service_factory().fetch_github_releases(
                repository=request.repository,
                limit=request.limit,
            )
        except ValueError as exc:
            return _error(status_code=400, code="invalid_github_source_request", message=str(exc))
        return _success(result.to_dict())

    @api.get("/api/v1/entities")
    def list_entities(enabled_only: bool = False, kind: str | None = None):
        try:
            result = entity_service_factory().list_entities(
                enabled_only=enabled_only,
                kind=kind,
            )
        except ValueError as exc:
            return _error(status_code=400, code="invalid_entity_list_request", message=str(exc))
        return _success(result.to_dict())

    @api.post("/api/v1/entities")
    def create_entity(request: EntityCreateRequest):
        try:
            entity = entity_service_factory().create_entity(
                name=request.name,
                kind=request.kind,
                aliases=request.aliases,
                entity_id=request.entity_id,
                enabled=request.enabled,
                metadata=request.metadata,
            )
        except ValueError as exc:
            return _error(status_code=400, code="invalid_entity_request", message=str(exc))
        return _success(entity.to_dict())

    @api.post("/api/v1/entities/{entity_id}/enable")
    def enable_entity(entity_id: str):
        return _set_entity_enabled(entity_id, enabled=True)

    @api.post("/api/v1/entities/{entity_id}/disable")
    def disable_entity(entity_id: str):
        return _set_entity_enabled(entity_id, enabled=False)

    @api.delete("/api/v1/entities/{entity_id}")
    def delete_entity(entity_id: str):
        deleted = entity_service_factory().delete_entity(entity_id)
        return _success({"entity_id": entity_id, "deleted": deleted})

    @api.get("/api/v1/entities/{entity_id}/report-matches")
    def entity_report_matches(entity_id: str, limit: int = 20, workflow_id: str | None = None):
        try:
            result = entity_service_factory().match_reports(
                entity_id,
                limit=limit,
                workflow_id=workflow_id,
            )
        except KeyError as exc:
            return _error(
                status_code=404,
                code="entity_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except ValueError as exc:
            return _error(status_code=400, code="invalid_entity_match_request", message=str(exc))
        return _success(result.to_dict())

    def _set_entity_enabled(entity_id: str, *, enabled: bool):
        try:
            entity = entity_service_factory().set_enabled(entity_id, enabled=enabled)
        except KeyError as exc:
            return _error(
                status_code=404,
                code="entity_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except ValueError as exc:
            return _error(status_code=400, code="invalid_entity_request", message=str(exc))
        return _success(entity.to_dict())

    @api.get("/api/v1/subscriptions")
    def list_subscriptions(enabled_only: bool = False, cadence: str | None = None):
        try:
            result = subscription_service_factory().list_topic_subscriptions(
                enabled_only=enabled_only,
                cadence=cadence,
            )
        except ValueError as exc:
            return _error(status_code=400, code="invalid_subscription_list_request", message=str(exc))
        return _success(result.to_dict())

    @api.post("/api/v1/subscriptions")
    def create_subscription(request: TopicSubscriptionCreateRequest):
        try:
            subscription = subscription_service_factory().create_topic_subscription(
                topic=request.topic,
                cadence=request.cadence,
                profile=request.profile,
                source_limit=request.source_limit,
                subscription_id=request.subscription_id,
                enabled=request.enabled,
                metadata=request.metadata,
            )
        except ValueError as exc:
            return _error(status_code=400, code="invalid_subscription_request", message=str(exc))
        return _success(subscription.to_dict())

    @api.post("/api/v1/subscriptions/{subscription_id}/enable")
    def enable_subscription(subscription_id: str):
        return _set_subscription_enabled(subscription_id, enabled=True)

    @api.post("/api/v1/subscriptions/{subscription_id}/disable")
    def disable_subscription(subscription_id: str):
        return _set_subscription_enabled(subscription_id, enabled=False)

    @api.delete("/api/v1/subscriptions/{subscription_id}")
    def delete_subscription(subscription_id: str):
        deleted = subscription_service_factory().delete_topic_subscription(subscription_id)
        return _success({"subscription_id": subscription_id, "deleted": deleted})

    def _set_subscription_enabled(subscription_id: str, *, enabled: bool):
        try:
            subscription = subscription_service_factory().set_enabled(subscription_id, enabled=enabled)
        except KeyError as exc:
            return _error(
                status_code=404,
                code="subscription_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except ValueError as exc:
            return _error(status_code=400, code="invalid_subscription_request", message=str(exc))
        return _success(subscription.to_dict())

    @api.get("/api/v1/mcp/catalog")
    def mcp_catalog():
        return _success(mcp_service_factory().catalog().to_dict())

    @api.get("/api/v1/mcp/capabilities")
    def mcp_capabilities():
        return _success(mcp_service_factory().capability_manifest().to_dict())

    @api.get("/api/v1/runs")
    def list_runs(limit: int = 20):
        return _success(run_inspection_service_factory().list_runs(limit=limit).to_dict())

    @api.get("/api/v1/runs/catalog/health")
    def get_run_catalog_health():
        return _success(run_inspection_service_factory().get_catalog_health().to_dict())

    @api.get("/api/v1/runs/compare")
    def compare_runs(base_run_id: str, target_run_id: str):
        try:
            result = run_inspection_service_factory().compare_runs(base_run_id, target_run_id)
        except FileNotFoundError as exc:
            return _error(
                status_code=404,
                code="run_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except ValueError as exc:
            return _error(status_code=400, code="invalid_run_compare_request", message=str(exc))
        return _success(result.to_dict())

    @api.get("/api/v1/runs/{run_id}")
    def get_run(run_id: str):
        try:
            result = run_inspection_service_factory().get_run(run_id)
        except FileNotFoundError as exc:
            return _error(
                status_code=404,
                code="run_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except ValueError as exc:
            return _error(status_code=400, code="invalid_run_id", message=str(exc))
        return _success(result.to_dict())

    @api.get("/api/v1/runs/{run_id}/manifest")
    def get_run_manifest(run_id: str):
        return get_run(run_id)

    @api.get("/api/v1/runs/{run_id}/events")
    def get_run_events(run_id: str, limit: int | None = None):
        try:
            result = run_inspection_service_factory().get_run_events(run_id, limit=limit)
        except FileNotFoundError as exc:
            return _error(
                status_code=404,
                code="run_events_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except ValueError as exc:
            return _error(status_code=400, code="invalid_run_events_request", message=str(exc))
        return _success(result.to_dict())

    @api.get(
        "/api/v1/runs/{run_id}/progress",
        responses={
            200: {
                "description": "Run progress as Server-Sent Events.",
                "content": {"text/event-stream": {"schema": {"type": "string"}}},
            }
        },
    )
    def stream_run_progress(run_id: str, limit: int | None = None):
        try:
            result = run_inspection_service_factory().get_run_events(run_id, limit=limit)
        except (AttributeError, FileNotFoundError) as exc:
            return _error(
                status_code=404,
                code="run_progress_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except ValueError as exc:
            return _error(status_code=400, code="invalid_run_progress_request", message=str(exc))
        return StreamingResponse(
            _run_progress_sse_frames(result.to_dict()),
            media_type="text/event-stream",
        )

    @api.get(
        "/api/v1/runs/{run_id}/events/stream",
        responses={
            200: {
                "description": "Run events as Server-Sent Events.",
                "content": {"text/event-stream": {"schema": {"type": "string"}}},
            }
        },
    )
    def stream_run_events(run_id: str, limit: int | None = None):
        try:
            result = run_inspection_service_factory().get_run_events(run_id, limit=limit)
        except FileNotFoundError as exc:
            return _error(
                status_code=404,
                code="run_events_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except ValueError as exc:
            return _error(status_code=400, code="invalid_run_events_request", message=str(exc))
        return StreamingResponse(
            _run_events_sse_frames(result.to_dict()),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @api.get("/api/v1/runs/{run_id}/replay")
    def replay_run(run_id: str):
        try:
            result = run_inspection_service_factory().replay_run(run_id)
        except FileNotFoundError as exc:
            return _error(
                status_code=404,
                code="run_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except ValueError as exc:
            return _error(status_code=400, code="invalid_run_replay_request", message=str(exc))
        return _success(result.to_dict())

    @api.get("/api/v1/runs/{run_id}/diagnostics")
    def get_run_diagnostics(run_id: str):
        try:
            result = run_inspection_service_factory().get_run_diagnostics(run_id)
        except FileNotFoundError as exc:
            return _error(
                status_code=404,
                code="run_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except ValueError as exc:
            return _error(status_code=400, code="invalid_run_diagnostics_request", message=str(exc))
        return _success(result.to_dict())

    @api.get("/api/v1/runs/{run_id}/health")
    def get_run_health(run_id: str):
        try:
            result = run_inspection_service_factory().get_run_health(run_id)
        except FileNotFoundError as exc:
            return _error(
                status_code=404,
                code="run_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except ValueError as exc:
            return _error(status_code=400, code="invalid_run_health_request", message=str(exc))
        return _success(result.to_dict())

    @api.get("/api/v1/runs/{run_id}/lineage")
    def list_run_lineage(run_id: str):
        try:
            result = storage_service_factory().list_lineage(run_id)
        except ValueError as exc:
            return _error(status_code=400, code="invalid_lineage_request", message=str(exc))
        return _success(result.to_dict())

    @api.get("/api/v1/runs/{run_id}/lineage/upstream")
    def run_lineage_upstream(run_id: str, target_type: str, target_id: str):
        try:
            result = storage_service_factory().lineage_upstream(
                run_id=run_id,
                target_type=target_type,
                target_id=target_id,
            )
        except ValueError as exc:
            return _error(status_code=400, code="invalid_lineage_request", message=str(exc))
        return _success(result.to_dict())

    @api.get("/api/v1/runs/{run_id}/lineage/downstream")
    def run_lineage_downstream(run_id: str, source_type: str, source_id: str):
        try:
            result = storage_service_factory().lineage_downstream(
                run_id=run_id,
                source_type=source_type,
                source_id=source_id,
            )
        except ValueError as exc:
            return _error(status_code=400, code="invalid_lineage_request", message=str(exc))
        return _success(result.to_dict())

    @api.get("/api/v1/runs/{run_id}/artifacts")
    def list_artifacts(run_id: str):
        try:
            result = artifact_service_factory().list_artifacts(run_id)
        except FileNotFoundError as exc:
            return _error(status_code=404, code="run_not_found", message=str(exc))
        except ValueError as exc:
            return _error(status_code=400, code="invalid_artifact_path", message=str(exc))
        return _success(result.to_dict())

    @api.get("/api/v1/runs/{run_id}/artifacts/{artifact_key}")
    def get_artifact(run_id: str, artifact_key: str):
        try:
            result = artifact_service_factory().get_artifact(run_id, artifact_key)
        except FileNotFoundError as exc:
            return _error(status_code=404, code="artifact_not_found", message=str(exc))
        except ValueError as exc:
            return _error(status_code=400, code="invalid_artifact_path", message=str(exc))
        return _success(result.to_dict())

    @api.get("/api/v1/artifacts")
    def list_artifacts_by_run(run_id: str):
        return list_artifacts(run_id)

    @api.get("/api/v1/artifacts/{artifact_id}")
    def get_artifact_by_id(artifact_id: str, run_id: str | None = None):
        try:
            resolved_run_id, artifact_key = _artifact_lookup_ids(artifact_id, run_id)
            result = artifact_service_factory().get_artifact(resolved_run_id, artifact_key)
        except FileNotFoundError as exc:
            return _error(status_code=404, code="artifact_not_found", message=str(exc))
        except ValueError as exc:
            return _error(status_code=400, code="invalid_artifact_id", message=str(exc))
        return _success(result.to_dict())

    @api.get("/api/v1/schedules")
    def list_schedules(include_disabled: bool = False):
        result = schedule_service_factory().list_schedules(enabled_only=not include_disabled)
        return _success(result.to_dict())

    @api.post("/api/v1/schedules/daily")
    def upsert_daily_schedule(request: DailyScheduleRequest):
        try:
            spec = ScheduleSpec(
                schedule_id=request.schedule_id,
                name=request.name,
                trigger_type=request.trigger_type,
                task_type="daily_intelligence.run",
                payload_template={
                    "profile": request.profile,
                    "topic": request.topic,
                    "source_limit": request.source_limit,
                },
                queue_name=request.queue_name,
                interval_seconds=(
                    request.interval_seconds if request.trigger_type == "interval" else None
                ),
                run_at=request.run_at if request.trigger_type == "interval" else None,
            )
        except ValueError as exc:
            return _error(status_code=400, code="invalid_schedule", message=str(exc))
        record = ScheduleRecord(spec=spec, next_run_at=spec.run_at)
        result = schedule_service_factory().upsert_schedule(record)
        return _success(result.to_dict())

    @api.post("/api/v1/schedules/tick")
    def tick_schedules(request: ScheduleTickRequest | None = None):
        actual_request = request or ScheduleTickRequest()
        result = schedule_service_factory().tick(
            now=actual_request.now,
            enabled_only=not actual_request.include_disabled,
        )
        return _success(result.to_dict())

    @api.post("/api/v1/schedules/{schedule_id}/trigger")
    def trigger_schedule(schedule_id: str, request: ManualScheduleTriggerRequest | None = None):
        actual_request = request or ManualScheduleTriggerRequest()
        try:
            result = schedule_service_factory().trigger_manual(
                schedule_id,
                now=actual_request.now,
            )
        except ScheduleNotFoundError as exc:
            return _error(status_code=404, code="schedule_not_found", message=str(exc))
        except ValueError as exc:
            return _error(status_code=400, code="invalid_schedule_trigger", message=str(exc))
        return _success(result.to_dict())

    @api.get("/api/v1/approvals")
    def list_approvals(status: str | None = None):
        try:
            result = approval_service_factory().list_approvals(status=status)
        except ValueError as exc:
            return _error(status_code=400, code="invalid_approval_status", message=str(exc))
        return _success(result.to_dict())

    @api.post("/api/v1/approvals")
    def submit_approval(request: ApprovalSubmitRequest):
        try:
            result = approval_service_factory().submit_request(
                requested_action=request.requested_action,
                risk_level=request.risk_level,
                reason=request.reason,
                payload=request.payload,
                task_id=request.task_id,
                run_id=request.run_id,
                requested_by=request.requested_by,
                expires_at=request.expires_at,
                metadata=request.metadata,
            )
        except ValueError as exc:
            return _error(status_code=400, code="invalid_approval", message=str(exc))
        return _success(result.to_dict())

    @api.get("/api/v1/approvals/{approval_id}")
    def get_approval(approval_id: str):
        try:
            result = approval_service_factory().get_approval(approval_id)
        except ApprovalNotFoundError as exc:
            return _error(status_code=404, code="approval_not_found", message=str(exc))
        return _success(result.to_dict())

    @api.post("/api/v1/approvals/{approval_id}/approve")
    def approve_approval(approval_id: str, request: ApprovalDecisionRequest):
        return _approval_decision_response(
            lambda: approval_service_factory().approve(
                approval_id,
                decided_by=request.decided_by,
                reason=request.reason,
            )
        )

    @api.post("/api/v1/approvals/{approval_id}/reject")
    def reject_approval(approval_id: str, request: ApprovalDecisionRequest):
        return _approval_decision_response(
            lambda: approval_service_factory().reject(
                approval_id,
                decided_by=request.decided_by,
                reason=request.reason,
            )
        )

    @api.post("/api/v1/approvals/{approval_id}/modify")
    def modify_approval(approval_id: str, request: ApprovalModifyRequest):
        return _approval_decision_response(
            lambda: approval_service_factory().modify(
                approval_id,
                decided_by=request.decided_by,
                modifications=request.modifications,
                reason=request.reason,
            )
        )

    return api


def _run_result_response(result) -> dict[str, Any]:
    payload = result.to_dict()
    response = _model_to_dict(_run_response_from_payload(payload))
    payload.update(response)
    payload["interface"] = response
    return payload


def _run_response_from_payload(payload: dict[str, Any]) -> RunResponse:
    run_status = str(payload.get("status") or "")
    output = payload.get("output")
    return RunResponse(
        run_id=payload.get("run_id"),
        status=_interface_status(run_status),
        run_status=run_status or None,
        report_status=_report_status_from_run_output(output),
        report_id=_report_id_from_run_output(output, run_id=payload.get("run_id")),
        manifest_ref=_manifest_ref_from_payload(payload),
        artifact_refs=_artifact_refs_from_payload(payload),
        diagnostics=_diagnostics_from_payload(payload),
        message=payload.get("error", {}).get("message") if isinstance(payload.get("error"), dict) else None,
    )


def _interface_status(run_status: str) -> str:
    normalized = run_status.strip().lower()
    if normalized in {"succeeded", "failed", "blocked", "cancelled"}:
        return normalized
    if normalized in {"running", "created", "pending"}:
        return "running"
    return "accepted"


def _report_id_from_run_output(output: Any, *, run_id: str | None = None) -> str | None:
    if not isinstance(output, dict):
        return None
    for key in ("report_id", "final_report_id"):
        value = output.get(key)
        if value:
            return str(value)
    report_status = _report_status_from_run_output(output)
    if run_id and report_status in {"final", "blocked"}:
        return f"{run_id}:{report_status}"
    return None


def _report_status_from_run_output(output: Any) -> str | None:
    if not isinstance(output, dict):
        return None
    value = output.get("report_status")
    if value:
        return str(value)
    report = output.get("report")
    if isinstance(report, dict) and report.get("status"):
        return str(report["status"])
    if output.get("final_report") is not None:
        return "final"
    if output.get("blocked_report") is not None:
        return "blocked"
    return None


def _manifest_ref_from_payload(payload: dict[str, Any]) -> ArtifactRef | None:
    manifest_path = payload.get("manifest_path")
    if not manifest_path:
        return None
    return ArtifactRef(
        artifact_id="manifest",
        run_id=_optional_str(payload.get("run_id")),
        artifact_type="manifest",
        path=str(manifest_path),
        content_type="application/json",
        redacted=True,
    )


def _artifact_refs_from_payload(payload: dict[str, Any]) -> list[ArtifactRef]:
    manifest_ref = _manifest_ref_from_payload(payload)
    manifest = _manifest_from_payload(payload)
    artifacts = manifest.get("artifacts") if manifest is not None else None
    refs: list[ArtifactRef] = []
    if manifest_ref is not None:
        refs.append(manifest_ref)
    if not isinstance(artifacts, dict):
        return refs
    run_id = _optional_str(payload.get("run_id"))
    for artifact_id, path in sorted(artifacts.items()):
        if not path:
            continue
        if manifest_ref is not None and str(artifact_id) == manifest_ref.artifact_id:
            continue
        refs.append(
            ArtifactRef(
                artifact_id=str(artifact_id),
                run_id=run_id,
                artifact_type=str(artifact_id),
                path=str(path),
                content_type=_artifact_content_type(str(path)),
                redacted=True,
            )
        )
    return refs


def _manifest_from_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    manifest = payload.get("manifest")
    if isinstance(manifest, dict):
        return manifest
    manifest_path = payload.get("manifest_path")
    if not manifest_path:
        return None
    try:
        loaded = json.loads(Path(str(manifest_path)).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _artifact_content_type(path: str) -> str:
    lowered = path.lower()
    if lowered.endswith(".json"):
        return "application/json"
    if lowered.endswith(".jsonl"):
        return "application/x-ndjson"
    if lowered.endswith(".md"):
        return "text/markdown"
    if lowered.endswith(".txt"):
        return "text/plain"
    return "application/octet-stream"


def _diagnostics_from_payload(payload: dict[str, Any]) -> list[str]:
    diagnostics = []
    error = payload.get("error")
    if isinstance(error, dict) and error.get("message"):
        diagnostics.append(str(error["message"]))
    manifest = payload.get("manifest")
    if isinstance(manifest, dict):
        route = manifest.get("quality_route")
        if route in {"blocked", "human_review"}:
            diagnostics.append(f"quality_route={route}")
    return diagnostics


def _artifact_lookup_ids(artifact_id: str, run_id: str | None) -> tuple[str, str]:
    artifact = artifact_id.strip()
    if not artifact:
        raise ValueError("artifact_id is required")
    if run_id:
        return run_id, artifact
    if ":" not in artifact:
        raise ValueError("run_id is required unless artifact_id uses run_id:artifact_key")
    resolved_run_id, artifact_key = artifact.split(":", 1)
    if not resolved_run_id or not artifact_key:
        raise ValueError("artifact_id must use run_id:artifact_key")
    return resolved_run_id, artifact_key


def _approval_decision_response(call):
    try:
        result = call()
    except ApprovalNotFoundError as exc:
        return _error(status_code=404, code="approval_not_found", message=str(exc))
    except ApprovalAlreadyDecidedError as exc:
        return _error(status_code=409, code="approval_already_decided", message=str(exc))
    except ValueError as exc:
        return _error(status_code=400, code="invalid_approval_decision", message=str(exc))
    return _success(result.to_dict())


def _success(data: dict) -> dict:
    return _model_to_dict(ApiResponse(success=True, data=data, request_id=_request_id()))


def _run_progress_sse_frames(payload: dict[str, Any]):
    run_id = str(payload.get("run_id") or "")
    for index, event in enumerate(payload.get("events") or []):
        yield _sse_frame(
            "run.progress",
            {
                "run_id": run_id,
                "sequence": index,
                "event": redact_sensitive_values(event if isinstance(event, dict) else {}),
            },
        )
    yield _sse_frame(
        "run.progress.done",
        {
            "run_id": run_id,
            "event_count": int(payload.get("event_count") or 0),
            "events_path": payload.get("events_path"),
        },
    )


def _run_events_sse_frames(payload: dict[str, Any]):
    run_id = str(payload.get("run_id") or "")
    for index, event in enumerate(payload.get("events") or []):
        event_payload = event if isinstance(event, dict) else {}
        event_type = str(event_payload.get("event_type") or "run.event")
        yield _sse_frame(
            event_type,
            {
                "run_id": run_id,
                "sequence": index,
                "event": redact_sensitive_values(event_payload),
            },
        )
    yield _sse_frame(
        "run.events.done",
        {
            "run_id": run_id,
            "event_count": int(payload.get("event_count") or 0),
            "events_path": payload.get("events_path"),
        },
    )


def _sse_frame(event_name: str, data: dict[str, Any]) -> str:
    return (
        f"event: {event_name}\n"
        f"data: {json.dumps(redact_sensitive_values(data), ensure_ascii=False, sort_keys=True)}\n\n"
    )


def _error(
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict | None = None,
    retryable: bool = False,
    user_action_required: bool = False,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = _request_id()
    payload = ApiResponse(
        success=False,
        error=ApiError(
            code=code,
            message=message,
            details=redact_sensitive_values(details or {}),
            retryable=retryable,
            user_action_required=user_action_required,
            request_id=request_id,
        ),
        request_id=request_id,
    )
    return JSONResponse(status_code=status_code, content=_model_to_dict(payload), headers=headers)


def _model_to_dict(model) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _provided_values(**values) -> dict:
    return {key: value for key, value in values.items() if value is not None}


def _optional_str(value) -> str | None:
    return str(value) if value is not None else None


def _request_id() -> str:
    return _REQUEST_ID_CONTEXT.get() or _new_request_id()


def _new_request_id() -> str:
    return f"req_{uuid4().hex}"


def _request_id_from_header(value: str | None) -> str | None:
    if value is None:
        return None
    request_id = value.strip()
    if not _REQUEST_ID_PATTERN.fullmatch(request_id):
        return None
    return request_id


def _normalize_api_token(api_token: str | None) -> str | None:
    if api_token is None:
        return None
    token = api_token.strip()
    return token or None


def _build_api_key_registry(
    *,
    api_token: str | None,
    api_keys: ApiKeyRoles | None,
    env: Mapping[str, str] | None = None,
) -> dict[str, list[str]]:
    registry: dict[str, list[str]] = {}
    legacy_token = _normalize_api_token(api_token)
    if legacy_token:
        registry[legacy_token] = ["admin"]
    for token, roles in (api_keys or {}).items():
        normalized = _normalize_api_token(str(token))
        if normalized:
            registry[normalized] = _normalize_roles(roles)
    for token, roles in _api_keys_from_env(env=env).items():
        registry[token] = roles
    return registry


def _api_keys_from_env(*, env: Mapping[str, str] | None = None) -> dict[str, list[str]]:
    values = env if env is not None else os.environ
    raw = (values.get("NEWS_API_KEYS") or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return _api_keys_from_text(raw)
    if not isinstance(parsed, dict):
        return {}
    registry: dict[str, list[str]] = {}
    for token, roles in parsed.items():
        normalized = _normalize_api_token(str(token))
        if normalized:
            registry[normalized] = _normalize_roles(roles)
    return registry


def _api_keys_from_text(raw: str) -> dict[str, list[str]]:
    registry: dict[str, list[str]] = {}
    for entry in raw.split(";"):
        text = entry.strip()
        if not text:
            continue
        separator = "=" if "=" in text else ":"
        token, found, roles = text.partition(separator)
        normalized = _normalize_api_token(token)
        if found and normalized:
            registry[normalized] = _normalize_roles(roles)
    return registry


def _normalize_roles(roles: Any) -> list[str]:
    if roles is None:
        return ["read-only"]
    if isinstance(roles, str):
        normalized = [item.strip() for item in roles.split(",") if item.strip()]
        return normalized or ["read-only"]
    if isinstance(roles, Sequence):
        normalized = [str(item).strip() for item in roles if str(item).strip()]
        return normalized or ["read-only"]
    role = str(roles).strip()
    return [role] if role else ["read-only"]


def _requires_api_auth(path: str) -> bool:
    return path.startswith("/api/")


def _authorized_api_actor(
    request: Request,
    api_keys: Mapping[str, list[str]],
) -> ActorContext | None:
    token = _bearer_token(request.headers.get("authorization"))
    if token is None:
        return None
    for expected_token, roles in api_keys.items():
        if hmac.compare_digest(token, expected_token):
            actor_id = (
                request.headers.get("x-api-client-id")
                or request.headers.get("x-news-actor")
                or _api_key_actor_id(expected_token)
            )
            return ActorContext(
                actor_id=str(actor_id),
                actor_type="mcp_client" if "mcp_client" in roles else "service",
                roles=list(roles),
                request_id=_request_id(),
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
            )
    return None


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer":
        return None
    stripped = token.strip()
    return stripped or None


def _api_key_actor_id(token: str) -> str:
    return f"api-key:{token[:6]}..."


def _required_api_permission(method: str, path: str) -> str | None:
    parts = [part for part in path.split("/") if part]
    if len(parts) < 3 or parts[0] != "api":
        return None
    resource = parts[2]
    method = method.upper()
    if resource == "admin":
        return "admin:diagnose"
    if resource == "mcp":
        return "mcp:read"
    if resource == "runs":
        return "runs:read" if method == "GET" else "runs:create"
    if resource == "reports":
        if method == "GET":
            return "reports:read"
        if path.endswith("/publish"):
            return "reports:publish"
        return "reports:read"
    if resource == "search":
        return "reports:read"
    if resource == "memory":
        return "memory:search"
    if resource == "sources":
        return "sources:read" if method == "GET" else "sources:write"
    if resource in {"workers", "queues"}:
        return "workers:read"
    if resource == "schedules":
        return "schedules:read" if method == "GET" else "schedules:write"
    if resource == "approvals":
        return "approvals:read" if method == "GET" else "approvals:decide"
    if resource == "entities":
        return "entities:read" if method == "GET" else "entities:write"
    if resource == "subscriptions":
        return "subscriptions:read" if method == "GET" else "subscriptions:write"
    if resource == "storage":
        return "storage:read"
    if resource == "artifacts":
        return "runs:read"
    return None


def _build_rate_limiter(
    limit: int | None,
    *,
    clock: Clock | None = None,
) -> InMemoryRateLimiter | None:
    if limit is None:
        return None
    return InMemoryRateLimiter(limit=limit, window_seconds=60, clock=clock)


def _client_rate_limit_key(request: Request) -> str:
    if request.client is None:
        return "unknown"
    return request.client.host or "unknown"


def _emit_api_audit(
    audit_emitter: AuditEmitter | None,
    request: Request,
    *,
    request_id: str,
    status_code: int,
    result: str,
) -> None:
    if audit_emitter is None:
        return
    path = request.url.path
    actor = getattr(request.state, "actor_context", None)
    if not isinstance(actor, ActorContext):
        actor = actor_context_from_headers(
            request.headers,
            request_id=request_id,
            ip_address=request.client.host if request.client else None,
        )
    audit_emitter.emit(
        actor=actor,
        action=_api_audit_action(request.method, path),
        resource_type=_api_resource_type(path),
        resource_id=_api_resource_id(path),
        result=result,  # type: ignore[arg-type]
        metadata={
            "method": request.method,
            "path": path,
            "status_code": status_code,
            "query": dict(request.query_params),
        },
    )


def _audit_result(status_code: int) -> str:
    if status_code in {401, 403, 429}:
        return "blocked"
    if status_code >= 400:
        return "failed"
    return "succeeded"


def _api_audit_action(method: str, path: str) -> str:
    prefix = "api_request"
    if path.startswith("/api/v1/approvals") and method == "POST":
        return "approval_decision_submitted" if any(
            path.endswith(suffix) for suffix in ("/approve", "/reject", "/modify")
        ) else "api_request_received"
    if path.startswith("/api/v1/artifacts"):
        return "artifact_read"
    if path.startswith("/api/v1/reports") and method == "GET":
        return "report_downloaded"
    return f"{prefix}_{method.lower()}"


def _api_resource_type(path: str) -> str:
    parts = [part for part in path.split("/") if part]
    if len(parts) >= 3 and parts[0] == "api":
        return parts[2]
    if parts:
        return parts[0]
    return "api"


def _api_resource_id(path: str) -> str | None:
    parts = [part for part in path.split("/") if part]
    if len(parts) >= 4 and parts[0] == "api":
        return parts[3]
    return None


def _optional_positive_int_env(name: str) -> int | None:
    value = os.environ.get(name)
    if value is None or value == "":
        return None
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _validation_error_details(errors: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "errors": [
            {
                "loc": [str(part) for part in error.get("loc", [])],
                "message": str(error.get("msg") or "invalid value"),
                "type": str(error.get("type") or "validation_error"),
            }
            for error in errors
        ]
    }


def _http_error_code(status_code: int) -> str:
    if status_code == 401:
        return "unauthorized"
    if status_code == 403:
        return "forbidden"
    if status_code == 404:
        return "not_found"
    if status_code == 409:
        return "conflict"
    if status_code == 429:
        return "rate_limited"
    if status_code >= 500:
        return "internal_error"
    return "invalid_request"


app = create_app(
    api_token=os.environ.get("NEWS_API_TOKEN"),
    api_keys=_api_keys_from_env(),
    api_rate_limit_per_minute=_optional_positive_int_env("NEWS_API_RATE_LIMIT_PER_MINUTE"),
)
