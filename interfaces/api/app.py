from __future__ import annotations

from typing import Callable
from uuid import uuid4

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from core.framework.workers.approval import ApprovalAlreadyDecidedError, ApprovalNotFoundError
from core.framework.workers.schedule_store import ScheduleNotFoundError, ScheduleRecord
from core.framework.workers.scheduler import ScheduleSpec
from interfaces.api.models import (
    ApiError,
    ApiResponse,
    ApprovalDecisionRequest,
    ApprovalModifyRequest,
    ApprovalSubmitRequest,
    DailyRunRequest,
    DailyScheduleRequest,
    ManualScheduleTriggerRequest,
    MemorySearchRequest,
    MemoryReindexRequest,
    ReportDetail,
    RunResponse,
    ScheduleTickRequest,
)
from interfaces.services.approval_service import ApprovalApplicationService
from interfaces.services.diagnose_service import DiagnosticApplicationService
from interfaces.services.memory_service import MemoryApplicationService
from interfaces.services.mcp_service import MCPApplicationService
from interfaces.services.report_service import ReportApplicationService
from interfaces.services.run_inspection_service import RunInspectionService
from interfaces.services.schedule_service import ScheduleApplicationService
from interfaces.services.source_service import SourceApplicationService
from interfaces.services.worker_service import WorkerApplicationService
from interfaces.services.artifact_service import ArtifactInspectionService


WorkerServiceFactory = Callable[[], WorkerApplicationService]
ReportServiceFactory = Callable[[], ReportApplicationService]
MemoryServiceFactory = Callable[[], MemoryApplicationService]
DiagnosticServiceFactory = Callable[[], DiagnosticApplicationService]
SourceServiceFactory = Callable[[], SourceApplicationService]
MCPServiceFactory = Callable[[], MCPApplicationService]
RunInspectionServiceFactory = Callable[[], RunInspectionService]
ArtifactInspectionServiceFactory = Callable[[], ArtifactInspectionService]
ScheduleServiceFactory = Callable[[], ScheduleApplicationService]
ApprovalServiceFactory = Callable[[], ApprovalApplicationService]


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
    schedule_service_factory: ScheduleServiceFactory = ScheduleApplicationService,
    approval_service_factory: ApprovalServiceFactory = ApprovalApplicationService,
) -> FastAPI:
    api = FastAPI(title="NewsRoom API", version="0.1.0")

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
            manifest_path=record.manifest_path,
        )
        return _success(_model_to_dict(data))

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

    @api.get("/api/v1/sources")
    def list_sources(include_disabled: bool = False):
        return _success(source_service_factory().list_sources(enabled_only=not include_disabled).to_dict())

    @api.get("/api/v1/sources/health")
    def source_health(include_disabled: bool = False):
        return _success(source_service_factory().source_health(enabled_only=not include_disabled).to_dict())

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
    return JSONResponse(status_code=status_code, content=_model_to_dict(payload))


def _model_to_dict(model) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _request_id() -> str:
    return f"req_{uuid4().hex}"


app = create_app()
