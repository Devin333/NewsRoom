from __future__ import annotations

import hmac
import os
import re
from contextvars import ContextVar
from datetime import datetime
from typing import Any, Callable
from uuid import uuid4

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.framework.workers.approval import ApprovalAlreadyDecidedError, ApprovalNotFoundError
from core.framework.workers.schedule_store import ScheduleNotFoundError, ScheduleRecord
from core.framework.workers.scheduler import ScheduleSpec
from interfaces.api.models import (
    ApiError,
    ApiResponse,
    ApprovalDecisionRequest,
    ApprovalModifyRequest,
    ArxivSourceFetchRequest,
    ApprovalSubmitRequest,
    DailyRunRequest,
    GithubReleaseFetchRequest,
    DailyScheduleRequest,
    ManualScheduleTriggerRequest,
    MemorySearchRequest,
    MemoryReindexRequest,
    ReportDetail,
    RunResponse,
    ScheduleTickRequest,
)
from interfaces.api.rate_limit import Clock, InMemoryRateLimiter
from interfaces.services.approval_service import ApprovalApplicationService
from interfaces.services.diagnose_service import DiagnosticApplicationService
from interfaces.services.memory_service import MemoryApplicationService
from interfaces.services.mcp_service import MCPApplicationService
from interfaces.services.report_service import ReportApplicationService
from interfaces.services.run_inspection_service import RunInspectionService
from interfaces.services.schedule_service import ScheduleApplicationService
from interfaces.services.source_service import SourceApplicationService
from interfaces.services.storage_service import StorageApplicationService
from interfaces.services.worker_service import WorkerApplicationService
from interfaces.services.artifact_service import ArtifactInspectionService
from storage.lifecycle import RetentionPolicy


WorkerServiceFactory = Callable[[], WorkerApplicationService]
ReportServiceFactory = Callable[[], ReportApplicationService]
MemoryServiceFactory = Callable[[], MemoryApplicationService]
DiagnosticServiceFactory = Callable[[], DiagnosticApplicationService]
SourceServiceFactory = Callable[[], SourceApplicationService]
MCPServiceFactory = Callable[[], MCPApplicationService]
RunInspectionServiceFactory = Callable[[], RunInspectionService]
ArtifactInspectionServiceFactory = Callable[[], ArtifactInspectionService]
StorageServiceFactory = Callable[[], StorageApplicationService]
ScheduleServiceFactory = Callable[[], ScheduleApplicationService]
ApprovalServiceFactory = Callable[[], ApprovalApplicationService]
REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_CONTEXT: ContextVar[str | None] = ContextVar("news_api_request_id", default=None)
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def create_app(
    *,
    worker_service_factory: WorkerServiceFactory = WorkerApplicationService,
    report_service_factory: ReportServiceFactory = ReportApplicationService,
    memory_service_factory: MemoryServiceFactory = MemoryApplicationService,
    diagnostic_service_factory: DiagnosticServiceFactory = DiagnosticApplicationService,
    source_service_factory: SourceServiceFactory = SourceApplicationService,
    mcp_service_factory: MCPServiceFactory = MCPApplicationService,
    run_inspection_service_factory: RunInspectionServiceFactory = RunInspectionService,
    artifact_service_factory: ArtifactInspectionServiceFactory = ArtifactInspectionService,
    storage_service_factory: StorageServiceFactory = StorageApplicationService,
    schedule_service_factory: ScheduleServiceFactory = ScheduleApplicationService,
    approval_service_factory: ApprovalServiceFactory = ApprovalApplicationService,
    api_token: str | None = None,
    api_rate_limit_per_minute: int | None = None,
    rate_limit_clock: Clock | None = None,
) -> FastAPI:
    api = FastAPI(title="NewsRoom API", version="0.1.0")
    resolved_api_token = _normalize_api_token(api_token)
    rate_limiter = _build_rate_limiter(api_rate_limit_per_minute, clock=rate_limit_clock)

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

    if resolved_api_token:

        @api.middleware("http")
        async def bearer_token_auth(request: Request, call_next):
            if _requires_api_auth(request.url.path) and not _is_authorized_bearer(
                request.headers.get("authorization"),
                resolved_api_token,
            ):
                return _error(
                    status_code=401,
                    code="unauthorized",
                    message="valid bearer token required",
                    user_action_required=True,
                    headers={"WWW-Authenticate": "Bearer"},
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

    @api.get("/api/v1/mcp/catalog")
    def mcp_catalog():
        return _success(mcp_service_factory().catalog().to_dict())

    @api.get("/api/v1/runs")
    def list_runs(limit: int = 20):
        return _success(run_inspection_service_factory().list_runs(limit=limit).to_dict())

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
    payload = ApiResponse(
        success=False,
        error=ApiError(
            code=code,
            message=message,
            details=details or {},
            retryable=retryable,
            user_action_required=user_action_required,
        ),
        request_id=_request_id(),
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


def _requires_api_auth(path: str) -> bool:
    return path.startswith("/api/")


def _is_authorized_bearer(authorization: str | None, expected_token: str) -> bool:
    if not authorization:
        return False
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer":
        return False
    return hmac.compare_digest(token.strip(), expected_token)


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
    api_rate_limit_per_minute=_optional_positive_int_env("NEWS_API_RATE_LIMIT_PER_MINUTE"),
)
