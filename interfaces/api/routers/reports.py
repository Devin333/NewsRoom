from __future__ import annotations

from fastapi import APIRouter

from interfaces.api.deps import ApiRouteHelpers, ApiServices
from interfaces.models import ReportActionRequest, ReportDetail


def create_router(services: ApiServices, helpers: ApiRouteHelpers) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/reports/latest")
    def latest_report():
        try:
            record = services.report_service_factory().latest_report()
        except FileNotFoundError as exc:
            return helpers.error(
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
        return helpers.success(helpers.model_to_dict(data))

    @router.get("/api/v1/reports")
    def list_reports(limit: int = 20, workflow_id: str | None = None):
        try:
            result = services.report_service_factory().list_reports(
                limit=limit,
                workflow_id=workflow_id,
            )
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_report_catalog", message=str(exc))
        return helpers.success(result.to_dict())

    @router.get("/api/v1/reports/{report_id}")
    def get_report(report_id: str):
        try:
            record = services.report_service_factory().get_report(report_id)
        except FileNotFoundError as exc:
            return helpers.error(
                status_code=404,
                code="report_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_report_id", message=str(exc))
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
        return helpers.success(helpers.model_to_dict(data))

    @router.get("/api/v1/reports/{report_id}/markdown")
    def get_report_markdown(report_id: str):
        try:
            result = services.report_service_factory().report_markdown(report_id)
        except FileNotFoundError as exc:
            return helpers.error(
                status_code=404,
                code="report_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_report_id", message=str(exc))
        return helpers.success(result.to_dict())

    @router.get("/api/v1/reports/{report_id}/quality")
    def get_report_quality(report_id: str):
        try:
            result = services.report_service_factory().report_quality(report_id)
        except FileNotFoundError as exc:
            return helpers.error(
                status_code=404,
                code="report_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_report_id", message=str(exc))
        return helpers.success(result.to_dict())

    @router.post("/api/v1/reports/{report_id}/request-review")
    def request_report_review(report_id: str, request: ReportActionRequest | None = None):
        actual_request = request or ReportActionRequest()
        try:
            action = services.report_service_factory().request_review(
                report_id,
                requested_by=actual_request.requested_by,
                reason=actual_request.reason,
                metadata=actual_request.metadata,
            )
            approval = services.approval_service_factory().submit_request(
                requested_action="review_report",
                risk_level="low",
                reason=actual_request.reason,
                payload={"report_id": report_id, **actual_request.metadata},
                requested_by=actual_request.requested_by,
            )
        except FileNotFoundError as exc:
            return helpers.error(status_code=404, code="report_not_found", message=str(exc))
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_report_action", message=str(exc))
        data = action.to_dict()
        data["approval"] = approval.to_dict()
        return helpers.success(data)

    @router.post("/api/v1/reports/{report_id}/publish")
    def publish_report(report_id: str, request: ReportActionRequest | None = None):
        actual_request = request or ReportActionRequest()
        try:
            action = services.report_service_factory().publish_report(
                report_id,
                requested_by=actual_request.requested_by,
                reason=actual_request.reason,
                metadata=actual_request.metadata,
            )
            approval = services.approval_service_factory().submit_request(
                requested_action="publish_report",
                risk_level="high",
                reason=actual_request.reason,
                payload={"report_id": report_id, **actual_request.metadata},
                requested_by=actual_request.requested_by,
            )
        except FileNotFoundError as exc:
            return helpers.error(status_code=404, code="report_not_found", message=str(exc))
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_report_action", message=str(exc))
        data = action.to_dict()
        data["approval"] = approval.to_dict()
        return helpers.success(data)

    @router.get("/api/v1/search/reports")
    def search_reports(q: str, limit: int = 20):
        try:
            result = services.report_service_factory().search_reports(query=q, limit=limit)
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_report_search", message=str(exc))
        return helpers.success(result.to_dict())

    return router


def _optional_str(value) -> str | None:
    return str(value) if value is not None else None
