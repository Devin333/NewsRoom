from __future__ import annotations

from fastapi import APIRouter

from interfaces.api.deps import ApiRouteHelpers, ApiServices
from interfaces.models import MemoryReindexRequest, MemorySearchRequest


def create_router(services: ApiServices, helpers: ApiRouteHelpers) -> APIRouter:
    router = APIRouter()

    @router.post("/api/v1/memory/search")
    def memory_search(request: MemorySearchRequest):
        result = services.memory_service_factory().search(
            text=request.query,
            collection=request.collection,
            limit=request.limit,
            filters=request.filters,
        )
        return helpers.success(result.to_dict())

    @router.post("/api/v1/memory/reindex")
    def memory_reindex(request: MemoryReindexRequest):
        try:
            result = services.memory_service_factory().reindex_run(
                request.run_id,
                topic=request.topic,
            )
        except FileNotFoundError as exc:
            return helpers.error(
                status_code=404,
                code="memory_reindex_source_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_memory_reindex_request", message=str(exc))
        return helpers.success(result.to_dict())

    @router.get("/api/v1/memory/{document_id}")
    def memory_document(document_id: str, collection: str = "report_sections"):
        try:
            result = services.memory_service_factory().get_document(document_id, collection=collection)
        except FileNotFoundError as exc:
            return helpers.error(
                status_code=404,
                code="memory_document_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_memory_document_request", message=str(exc))
        return helpers.success(result.to_dict())

    return router
