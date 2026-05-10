from __future__ import annotations

from typing import Callable
from uuid import uuid4

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from interfaces.api.models import (
    ApiError,
    ApiResponse,
    DailyRunRequest,
    MemorySearchRequest,
    ReportDetail,
    RunResponse,
)
from interfaces.services.memory_service import MemoryApplicationService
from interfaces.services.report_service import ReportApplicationService
from interfaces.services.worker_service import WorkerApplicationService


WorkerServiceFactory = Callable[[], WorkerApplicationService]
ReportServiceFactory = Callable[[], ReportApplicationService]
MemoryServiceFactory = Callable[[], MemoryApplicationService]


def create_app(
    *,
    worker_service_factory: WorkerServiceFactory = WorkerApplicationService,
    report_service_factory: ReportServiceFactory = ReportApplicationService,
    memory_service_factory: MemoryServiceFactory = MemoryApplicationService,
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

    return api


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
