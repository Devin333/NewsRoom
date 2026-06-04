from __future__ import annotations

from fastapi import APIRouter

from framework.workers.approval import ApprovalNotFoundError
from interfaces.api.deps import ApiRouteHelpers, ApiServices
from interfaces.models import (
    ApprovalDecisionRequest,
    ApprovalModifyRequest,
    ApprovalResumeContextRequest,
    ApprovalSubmitRequest,
)


def create_router(services: ApiServices, helpers: ApiRouteHelpers) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/approvals")
    def list_approvals(status: str | None = None):
        try:
            result = services.approval_service_factory().list_approvals(status=status)
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_approval_status", message=str(exc))
        return helpers.success(result.to_dict())

    @router.post("/api/v1/approvals")
    def submit_approval(request: ApprovalSubmitRequest):
        try:
            result = services.approval_service_factory().submit_request(
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
            return helpers.error(status_code=400, code="invalid_approval", message=str(exc))
        return helpers.success(result.to_dict())

    @router.get("/api/v1/approvals/{approval_id}")
    def get_approval(approval_id: str):
        try:
            result = services.approval_service_factory().get_approval(approval_id)
        except ApprovalNotFoundError as exc:
            return helpers.error(status_code=404, code="approval_not_found", message=str(exc))
        return helpers.success(result.to_dict())

    @router.post("/api/v1/approvals/{approval_id}/resume-context")
    def approval_resume_context(
        approval_id: str,
        request: ApprovalResumeContextRequest | None = None,
    ):
        actual_request = request or ApprovalResumeContextRequest()
        try:
            result = services.approval_service_factory().build_resume_context(
                approval_id,
                decision_key=actual_request.decision_key,
            )
        except ApprovalNotFoundError as exc:
            return helpers.error(status_code=404, code="approval_not_found", message=str(exc))
        except ValueError as exc:
            return helpers.error(
                status_code=400,
                code="approval_resume_context_unavailable",
                message=str(exc),
            )
        return helpers.success(result.to_dict())

    @router.post("/api/v1/approvals/{approval_id}/approve")
    def approve_approval(approval_id: str, request: ApprovalDecisionRequest):
        return helpers.approval_decision_response(
            lambda: services.approval_service_factory().approve(
                approval_id,
                decided_by=request.decided_by,
                reason=request.reason,
            )
        )

    @router.post("/api/v1/approvals/{approval_id}/reject")
    def reject_approval(approval_id: str, request: ApprovalDecisionRequest):
        return helpers.approval_decision_response(
            lambda: services.approval_service_factory().reject(
                approval_id,
                decided_by=request.decided_by,
                reason=request.reason,
            )
        )

    @router.post("/api/v1/approvals/{approval_id}/modify")
    def modify_approval(approval_id: str, request: ApprovalModifyRequest):
        return helpers.approval_decision_response(
            lambda: services.approval_service_factory().modify(
                approval_id,
                decided_by=request.decided_by,
                modifications=request.modifications,
                reason=request.reason,
            )
        )

    return router
