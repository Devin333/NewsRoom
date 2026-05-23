from __future__ import annotations

from fastapi import APIRouter

from interfaces.api.deps import ApiRouteHelpers, ApiServices
from interfaces.models import (
    ArxivSourceFetchRequest,
    GithubReleaseFetchRequest,
    SourceCategoryFetchRequest,
    SourceFetchRequest,
    SourcePriorityFetchRequest,
    SourceProbeRequest,
    SourceTopicFetchRequest,
)


def create_router(services: ApiServices, helpers: ApiRouteHelpers) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/sources")
    def list_sources(include_disabled: bool = False):
        return helpers.success(
            services.source_service_factory().list_sources(enabled_only=not include_disabled).to_dict()
        )

    @router.get("/api/v1/sources/health")
    def source_health(include_disabled: bool = False):
        return helpers.success(
            services.source_service_factory().source_health(enabled_only=not include_disabled).to_dict()
        )

    @router.get("/api/v1/sources/validation")
    def validate_sources():
        return helpers.success(services.source_service_factory().validate_sources().to_dict())

    @router.get("/api/v1/sources/categories")
    def source_categories():
        return helpers.success(services.source_service_factory().source_categories())

    @router.get("/api/v1/sources/priorities")
    def source_priorities():
        return helpers.success(services.source_service_factory().source_priorities())

    @router.get("/api/v1/sources/{source_id}")
    def get_source(source_id: str):
        try:
            result = services.source_service_factory().get_source(source_id)
        except KeyError as exc:
            return helpers.error(
                status_code=404,
                code="source_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_source_request", message=str(exc))
        return helpers.success(result.to_dict())

    @router.post("/api/v1/sources/{source_id}/probe")
    def probe_source(source_id: str, request: SourceProbeRequest | None = None):
        actual_request = request or SourceProbeRequest()
        try:
            result = services.source_service_factory().check_source_health(
                source_id=source_id,
                enabled_only=not actual_request.include_disabled,
                limit=actual_request.limit,
                force=actual_request.force,
            )
        except KeyError as exc:
            return helpers.error(
                status_code=404,
                code="source_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_source_probe", message=str(exc))
        return helpers.success(result.to_dict())

    @router.post("/api/v1/sources/arxiv/fetch")
    def fetch_arxiv_source(request: ArxivSourceFetchRequest):
        try:
            result = services.source_service_factory().fetch_arxiv(query=request.query, limit=request.limit)
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_arxiv_source_request", message=str(exc))
        return helpers.success(result.to_dict())

    @router.post("/api/v1/sources/github/releases")
    def fetch_github_releases(request: GithubReleaseFetchRequest):
        try:
            result = services.source_service_factory().fetch_github_releases(
                repository=request.repository,
                limit=request.limit,
            )
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_github_source_request", message=str(exc))
        return helpers.success(result.to_dict())

    @router.post("/api/v1/sources/fetch")
    def fetch_source(request: SourceFetchRequest):
        try:
            result = services.source_service_factory().fetch_source(
                source_id=request.source_id,
                limit=request.limit,
                query=request.query,
                force=request.force,
            )
        except KeyError as exc:
            return helpers.error(
                status_code=404,
                code="source_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_source_fetch_request", message=str(exc))
        return helpers.success(result.to_dict())

    @router.post("/api/v1/sources/fetch-category")
    def fetch_category(request: SourceCategoryFetchRequest):
        try:
            result = services.source_service_factory().fetch_category(
                category=request.category,
                limit_per_source=request.limit_per_source,
                enabled_only=request.enabled_only,
                priority=request.priority,
                language=request.language,
                region=request.region,
                force=request.force,
            )
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_source_category_fetch_request", message=str(exc))
        return helpers.success(result.to_dict())

    @router.post("/api/v1/sources/fetch-priority")
    def fetch_priority(request: SourcePriorityFetchRequest):
        try:
            result = services.source_service_factory().fetch_priority(
                priority=request.priority,
                limit_per_source=request.limit_per_source,
                enabled_only=request.enabled_only,
                force=request.force,
            )
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_source_priority_fetch_request", message=str(exc))
        return helpers.success(result.to_dict())

    @router.post("/api/v1/sources/fetch-topic")
    def fetch_topic(request: SourceTopicFetchRequest):
        try:
            result = services.source_service_factory().fetch_topic_sources(
                topic=request.topic,
                limit_per_source=request.limit_per_source,
                enabled_only=request.enabled_only,
                category=request.category,
                priority=request.priority,
                language=request.language,
                region=request.region,
                force=request.force,
            )
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_source_topic_fetch_request", message=str(exc))
        return helpers.success(result.to_dict())

    return router
