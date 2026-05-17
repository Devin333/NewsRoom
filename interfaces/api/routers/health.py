from __future__ import annotations

from fastapi import APIRouter

from interfaces.api.deps import ApiRouteHelpers, ApiServices


def create_router(services: ApiServices, helpers: ApiRouteHelpers) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    def health() -> dict:
        return helpers.success({"status": "ok", "service": "newsroom-api"})

    @router.get("/health/live")
    def live_health() -> dict:
        return helpers.success({"status": "ok", "service": "newsroom-api", "live": True})

    @router.get("/health/ready")
    def ready_health() -> dict:
        return helpers.success({"status": "ok", "service": "newsroom-api", "ready": True})

    @router.get("/health/dependencies")
    def dependency_health() -> dict:
        return helpers.success(services.diagnostic_service_factory().run().to_dict())

    @router.get("/api/v1/admin/diagnose")
    def diagnose():
        return helpers.success(services.diagnostic_service_factory().run().to_dict())

    return router
