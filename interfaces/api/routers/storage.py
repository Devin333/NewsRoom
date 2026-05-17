from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter

from interfaces.api.deps import ApiRouteHelpers, ApiServices
from storage.lifecycle import RetentionPolicy


def create_router(services: ApiServices, helpers: ApiRouteHelpers) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/storage/metrics")
    def storage_metrics():
        return helpers.success(services.storage_service_factory().metrics().to_dict())

    @router.get("/api/v1/storage/retention/plan")
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
                helpers.provided_values(
                    raw_source_retention_days=raw_source_retention_days,
                    llm_artifact_retention_days=llm_artifact_retention_days,
                    run_artifact_retention_days=run_artifact_retention_days,
                    report_retention_days=report_retention_days,
                    evidence_retention_days=evidence_retention_days,
                    vector_retention_days=vector_retention_days,
                )
            )
            result = services.storage_service_factory().plan_retention(
                policy=policy,
                run_id=run_id,
                now=now,
            )
        except ValueError as exc:
            return helpers.error(
                status_code=400,
                code="invalid_storage_retention_request",
                message=str(exc),
            )
        return helpers.success(result.to_dict())

    return router
