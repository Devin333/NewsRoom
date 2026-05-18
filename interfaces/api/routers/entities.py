from __future__ import annotations

from fastapi import APIRouter

from interfaces.api.deps import ApiRouteHelpers, ApiServices
from interfaces.models import EntityCreateRequest


def create_router(services: ApiServices, helpers: ApiRouteHelpers) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/entities")
    def list_entities(enabled_only: bool = False, kind: str | None = None):
        try:
            result = services.entity_service_factory().list_entities(
                enabled_only=enabled_only,
                kind=kind,
            )
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_entity_list_request", message=str(exc))
        return helpers.success(result.to_dict())

    @router.post("/api/v1/entities")
    def create_entity(request: EntityCreateRequest):
        try:
            entity = services.entity_service_factory().create_entity(
                name=request.name,
                kind=request.kind,
                aliases=request.aliases,
                entity_id=request.entity_id,
                enabled=request.enabled,
                metadata=request.metadata,
            )
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_entity_request", message=str(exc))
        return helpers.success(entity.to_dict())

    @router.post("/api/v1/entities/{entity_id}/enable")
    def enable_entity(entity_id: str):
        return _set_entity_enabled(entity_id, enabled=True)

    @router.post("/api/v1/entities/{entity_id}/disable")
    def disable_entity(entity_id: str):
        return _set_entity_enabled(entity_id, enabled=False)

    @router.delete("/api/v1/entities/{entity_id}")
    def delete_entity(entity_id: str):
        deleted = services.entity_service_factory().delete_entity(entity_id)
        return helpers.success({"entity_id": entity_id, "deleted": deleted})

    @router.get("/api/v1/entities/{entity_id}/report-matches")
    def entity_report_matches(
        entity_id: str,
        limit: int = 20,
        workflow_id: str | None = None,
        workflow_family: str | None = None,
    ):
        try:
            result = services.entity_service_factory().match_reports(
                entity_id,
                limit=limit,
                workflow_id=workflow_id,
                workflow_family=workflow_family,
            )
        except KeyError as exc:
            return helpers.error(
                status_code=404,
                code="entity_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_entity_match_request", message=str(exc))
        return helpers.success(result.to_dict())

    def _set_entity_enabled(entity_id: str, *, enabled: bool):
        try:
            entity = services.entity_service_factory().set_enabled(entity_id, enabled=enabled)
        except KeyError as exc:
            return helpers.error(
                status_code=404,
                code="entity_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_entity_request", message=str(exc))
        return helpers.success(entity.to_dict())

    return router
