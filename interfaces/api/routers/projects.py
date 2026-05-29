from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from business.projects.dto import (
    CaseSearchQuery,
    InteractionRequest,
    LabAnswerRequest,
    LabSessionRequest,
    ProjectListQuery,
    ToolCompareRequest,
    ToolRecommendRequest,
    ToolSearchQuery,
    WatchlistCreateRequest,
    WatchlistPatchRequest,
)
from interfaces.api.deps import ApiRouteHelpers, ApiServices
from interfaces.services.project_service import (
    ProjectCaseNotFoundError,
    ProjectCollectionNotFoundError,
    ProjectLabSessionNotFoundError,
    ProjectNotFoundError,
    ProjectWatchlistItemNotFoundError,
)


class LabAnswerBody(BaseModel):
    question_id: str = Field(alias="questionId")
    answer: Any


def create_router(services: ApiServices, helpers: ApiRouteHelpers) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/projects")
    def projects_home(limit: int = 6, user_id: str | None = None):
        return helpers.success(services.project_service_factory().get_home(limit=limit, user_id=user_id))

    @router.get("/api/v1/projects/hot")
    def list_hot_projects(
        q: str | None = None,
        category: str | None = None,
        tag: str | None = None,
        source: str | None = None,
        project_type: str | None = None,
        page: int = 1,
        page_size: int = 24,
        limit: int | None = None,
    ):
        query = ProjectListQuery(
            q=q,
            category=category,
            tag=tag,
            source=source,
            project_type=project_type,
            sort="hot",
            page=page,
            page_size=page_size,
            limit=limit,
        )
        return helpers.success(services.project_service_factory().list_hot(query))

    @router.get("/api/v1/projects/rising")
    def list_rising_projects(
        q: str | None = None,
        category: str | None = None,
        tag: str | None = None,
        source: str | None = None,
        project_type: str | None = None,
        page: int = 1,
        page_size: int = 24,
        limit: int | None = None,
    ):
        query = ProjectListQuery(
            q=q,
            category=category,
            tag=tag,
            source=source,
            project_type=project_type,
            sort="rising",
            page=page,
            page_size=page_size,
            limit=limit,
        )
        return helpers.success(services.project_service_factory().list_rising(query))

    @router.get("/api/v1/projects/tools")
    def search_project_tools(
        q: str | None = None,
        category: str | None = None,
        use_case: str | None = None,
        input_type: str | None = None,
        output_type: str | None = None,
        deployment: str | None = None,
        difficulty: str | None = None,
        has_api: bool | None = None,
        has_cli: bool | None = None,
        has_python_sdk: bool | None = None,
        has_docker: bool | None = None,
        page: int = 1,
        page_size: int = 24,
        limit: int | None = None,
    ):
        query = ToolSearchQuery(
            q=q,
            category=category,
            use_case=use_case,
            input_type=input_type,
            output_type=output_type,
            deployment=deployment,
            difficulty=difficulty,
            has_api=has_api,
            has_cli=has_cli,
            has_python_sdk=has_python_sdk,
            has_docker=has_docker,
            page=page,
            page_size=page_size,
            limit=limit,
        )
        return helpers.success(services.project_service_factory().search_tools(query))

    @router.post("/api/v1/projects/tools/compare")
    def compare_project_tools(request: ToolCompareRequest):
        return helpers.success(services.project_service_factory().compare_tools(request))

    @router.post("/api/v1/projects/tools/recommend")
    def recommend_project_tools(request: ToolRecommendRequest):
        try:
            return helpers.success(services.project_service_factory().recommend_tools(request))
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_project_tool_recommendation", message=str(exc))

    @router.get("/api/v1/projects/tools/{project_id}")
    def get_project_tool(project_id: str):
        try:
            return helpers.success(services.project_service_factory().get_tool_detail(project_id))
        except ProjectNotFoundError as exc:
            return helpers.error(status_code=404, code="project_tool_not_found", message=str(exc))

    @router.get("/api/v1/projects/cases")
    def search_project_cases(
        q: str | None = None,
        business_domain: str | None = None,
        module_type: str | None = None,
        pattern: str | None = None,
        migration_level: str | None = None,
        difficulty: str | None = None,
        page: int = 1,
        page_size: int = 24,
        limit: int | None = None,
    ):
        query = CaseSearchQuery(
            q=q,
            business_domain=business_domain,
            module_type=module_type,
            pattern=pattern,
            migration_level=migration_level,
            difficulty=difficulty,
            page=page,
            page_size=page_size,
            limit=limit,
        )
        return helpers.success(services.project_service_factory().search_cases(query))

    @router.get("/api/v1/projects/cases/{case_id}")
    def get_project_case(case_id: str):
        try:
            return helpers.success(services.project_service_factory().get_case_detail(case_id))
        except ProjectCaseNotFoundError as exc:
            return helpers.error(status_code=404, code="project_case_not_found", message=str(exc))

    @router.post("/api/v1/projects/lab/sessions")
    def start_project_lab_session(request: LabSessionRequest):
        try:
            return helpers.success({"session": services.project_service_factory().start_lab_session(request)})
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_project_lab_request", message=str(exc))

    @router.post("/api/v1/projects/lab/sessions/{session_id}/answer")
    def answer_project_lab_question(session_id: str, request: LabAnswerRequest):
        try:
            return helpers.success({"session": services.project_service_factory().answer_lab_question(session_id, request)})
        except ProjectLabSessionNotFoundError as exc:
            return helpers.error(status_code=404, code="project_lab_session_not_found", message=str(exc))

    @router.post("/api/v1/projects/lab/sessions/{session_id}/generate-solution")
    def generate_project_lab_solution(session_id: str):
        try:
            return helpers.success(services.project_service_factory().generate_lab_solution(session_id))
        except ProjectLabSessionNotFoundError as exc:
            return helpers.error(status_code=404, code="project_lab_session_not_found", message=str(exc))

    @router.get("/api/v1/projects/collections")
    def list_project_collections():
        return helpers.success(services.project_service_factory().list_collections())

    @router.get("/api/v1/projects/collections/{slug}")
    def get_project_collection(slug: str):
        try:
            return helpers.success(services.project_service_factory().get_collection(slug))
        except ProjectCollectionNotFoundError as exc:
            return helpers.error(status_code=404, code="project_collection_not_found", message=str(exc))

    @router.get("/api/v1/projects/watchlist")
    def list_project_watchlist(user_id: str | None = None):
        return helpers.success(services.project_service_factory().list_watchlist(user_id=user_id))

    @router.post("/api/v1/projects/watchlist")
    def add_project_watchlist_item(request: WatchlistCreateRequest):
        try:
            return helpers.success({"item": services.project_service_factory().add_watchlist(request)})
        except ValueError as exc:
            return helpers.error(status_code=404, code="project_not_found", message=str(exc))

    @router.patch("/api/v1/projects/watchlist/{item_id}")
    def patch_project_watchlist_item(item_id: str, request: WatchlistPatchRequest):
        try:
            return helpers.success({"item": services.project_service_factory().patch_watchlist(item_id, request)})
        except ProjectWatchlistItemNotFoundError as exc:
            return helpers.error(status_code=404, code="project_watchlist_item_not_found", message=str(exc))

    @router.delete("/api/v1/projects/watchlist/{item_id}")
    def delete_project_watchlist_item(item_id: str):
        try:
            return helpers.success(services.project_service_factory().delete_watchlist(item_id))
        except ProjectWatchlistItemNotFoundError as exc:
            return helpers.error(status_code=404, code="project_watchlist_item_not_found", message=str(exc))

    @router.post("/api/v1/projects/interactions")
    def record_project_interaction(request: InteractionRequest):
        return helpers.success({"event": services.project_service_factory().record_interaction(request)})

    @router.get("/api/v1/projects/{project_id}")
    def get_project(project_id: str):
        try:
            return helpers.success(services.project_service_factory().get_project(project_id))
        except ProjectNotFoundError as exc:
            return helpers.error(status_code=404, code="project_not_found", message=str(exc))

    return router
