from __future__ import annotations

from fastapi import APIRouter, Query

from interfaces.api.deps import ApiRouteHelpers, ApiServices


def create_router(services: ApiServices, helpers: ApiRouteHelpers) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/workers")
    def list_workers(stale_after_seconds: int = 60):
        try:
            result = services.worker_service_factory().list_worker_status(
                stale_after_seconds=stale_after_seconds
            )
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_worker_status_request", message=str(exc))
        return helpers.success(result.to_dict())

    @router.get("/api/v1/workers/{worker_id}")
    def get_worker(worker_id: str, stale_after_seconds: int = 60):
        try:
            result = services.worker_service_factory().list_worker_status(
                worker_id=worker_id,
                stale_after_seconds=stale_after_seconds,
            )
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_worker_status_request", message=str(exc))
        return helpers.success(result.to_dict())

    @router.get("/api/v1/queues")
    def list_queues(queue_name: list[str] | None = Query(default=None)):
        try:
            result = services.worker_service_factory().queue_status(queue_names=queue_name)
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_queue_status_request", message=str(exc))
        return helpers.success(result.to_dict())

    return router
