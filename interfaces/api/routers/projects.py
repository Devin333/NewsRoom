from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from backend.projects.dto import (
    CaseExplainRequest,
    CaseMapRequest,
    CaseSearchQuery,
    CollectionCreateRequest,
    CollectionGenerateRequest,
    CollectionItemCreateRequest,
    InteractionRequest,
    LabAnswerRequest,
    LabNodeExplainRequest,
    LabSaveRequest,
    LabSessionRequest,
    ProjectListQuery,
    ToolCompareRequest,
    ToolRecommendRequest,
    ToolSearchQuery,
    WatchlistCreateRequest,
    WatchlistPatchRequest,
)
from interfaces.api.deps import ApiRouteHelpers, ApiServices, get_actor_context
from interfaces.services.project_service import (
    ProjectCaseNotFoundError,
    ProjectCollectionNotFoundError,
    ProjectLabNodeNotFoundError,
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
    def projects_home(http_request: Request, limit: int = 6):
        return helpers.success(services.project_service_factory().get_home(limit=limit, user_id=_actor_user_id(http_request)))

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

    @router.post("/api/v1/projects/cases/{case_id}/explain")
    def explain_project_case(case_id: str, request: CaseExplainRequest):
        try:
            return helpers.success(services.project_service_factory().explain_case(case_id, request))
        except ProjectCaseNotFoundError as exc:
            return helpers.error(status_code=404, code="project_case_not_found", message=str(exc))

    @router.post("/api/v1/projects/cases/{case_id}/map-to-context")
    def map_project_case_to_context(case_id: str, request: CaseMapRequest):
        try:
            return helpers.success(services.project_service_factory().map_case_to_context(case_id, request))
        except ProjectCaseNotFoundError as exc:
            return helpers.error(status_code=404, code="project_case_not_found", message=str(exc))

    @router.post("/api/v1/projects/lab/sessions")
    def start_project_lab_session(http_request: Request, request: LabSessionRequest):
        try:
            return helpers.success({"session": services.project_service_factory().start_lab_session(_with_user_id(request, http_request))})
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_project_lab_request", message=str(exc))

    @router.get("/api/v1/projects/lab/sessions/{session_id}")
    def get_project_lab_session(session_id: str):
        try:
            return helpers.success({"session": services.project_service_factory().get_lab_session(session_id)})
        except ProjectLabSessionNotFoundError as exc:
            return helpers.error(status_code=404, code="project_lab_session_not_found", message=str(exc))

    @router.post("/api/v1/projects/lab/sessions/{session_id}/answer")
    def answer_project_lab_question(session_id: str, request: LabAnswerRequest):
        try:
            return helpers.success({"session": services.project_service_factory().answer_lab_question(session_id, request)})
        except ProjectLabSessionNotFoundError as exc:
            return helpers.error(status_code=404, code="project_lab_session_not_found", message=str(exc))

    @router.post("/api/v1/projects/lab/sessions/{session_id}/explain-node")
    def explain_project_lab_node(session_id: str, request: LabNodeExplainRequest):
        try:
            return helpers.success(services.project_service_factory().explain_lab_node(session_id, request))
        except ProjectLabNodeNotFoundError as exc:
            return helpers.error(status_code=404, code="project_lab_node_not_found", message=str(exc))

    @router.post("/api/v1/projects/lab/sessions/{session_id}/generate-solution")
    def generate_project_lab_solution(session_id: str):
        try:
            return helpers.success(services.project_service_factory().generate_lab_solution(session_id))
        except ProjectLabSessionNotFoundError as exc:
            return helpers.error(status_code=404, code="project_lab_session_not_found", message=str(exc))

    @router.post("/api/v1/projects/lab/sessions/{session_id}/save")
    def save_project_lab_session(session_id: str, request: LabSaveRequest):
        try:
            return helpers.success({"session": services.project_service_factory().save_lab_session(session_id, request)})
        except ProjectLabSessionNotFoundError as exc:
            return helpers.error(status_code=404, code="project_lab_session_not_found", message=str(exc))

    @router.get("/api/v1/projects/collections")
    def list_project_collections():
        return helpers.success(services.project_service_factory().list_collections())

    @router.post("/api/v1/projects/collections")
    def create_project_collection(http_request: Request, request: CollectionCreateRequest):
        try:
            return helpers.success(services.project_service_factory().create_collection(_with_created_by(request, http_request)))
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_project_collection", message=str(exc))

    @router.post("/api/v1/projects/collections/generate")
    def generate_project_collection(http_request: Request, request: CollectionGenerateRequest):
        try:
            return helpers.success(services.project_service_factory().generate_collection(_with_created_by(request, http_request)))
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_project_collection_generation", message=str(exc))

    @router.get("/api/v1/projects/collections/{slug}")
    def get_project_collection(slug: str):
        try:
            return helpers.success(services.project_service_factory().get_collection(slug))
        except ProjectCollectionNotFoundError as exc:
            return helpers.error(status_code=404, code="project_collection_not_found", message=str(exc))

    @router.post("/api/v1/projects/collections/{collection_id}/items")
    def add_project_collection_item(collection_id: str, request: CollectionItemCreateRequest):
        try:
            return helpers.success(services.project_service_factory().add_collection_item(collection_id, request))
        except ProjectCollectionNotFoundError as exc:
            return helpers.error(status_code=404, code="project_collection_not_found", message=str(exc))
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_project_collection_item", message=str(exc))

    @router.get("/api/v1/projects/watchlist")
    def list_project_watchlist(http_request: Request):
        return helpers.success(services.project_service_factory().list_watchlist(user_id=_actor_user_id(http_request)))

    @router.post("/api/v1/projects/watchlist")
    def add_project_watchlist_item(http_request: Request, request: WatchlistCreateRequest):
        try:
            return helpers.success({"item": services.project_service_factory().add_watchlist(_with_user_id(request, http_request))})
        except ValueError as exc:
            return helpers.error(status_code=404, code="project_not_found", message=str(exc))

    @router.patch("/api/v1/projects/watchlist/{item_id}")
    def patch_project_watchlist_item(http_request: Request, item_id: str, request: WatchlistPatchRequest):
        try:
            return helpers.success({"item": services.project_service_factory().patch_watchlist(item_id, request, user_id=_actor_user_id(http_request))})
        except ProjectWatchlistItemNotFoundError as exc:
            return helpers.error(status_code=404, code="project_watchlist_item_not_found", message=str(exc))

    @router.post("/api/v1/projects/watchlist/{item_id}/refresh")
    def refresh_project_watchlist_item(http_request: Request, item_id: str):
        try:
            return helpers.success(services.project_service_factory().refresh_watchlist(item_id, user_id=_actor_user_id(http_request)))
        except ProjectWatchlistItemNotFoundError as exc:
            return helpers.error(status_code=404, code="project_watchlist_item_not_found", message=str(exc))

    @router.delete("/api/v1/projects/watchlist/{item_id}")
    def delete_project_watchlist_item(http_request: Request, item_id: str):
        try:
            return helpers.success(services.project_service_factory().delete_watchlist(item_id, user_id=_actor_user_id(http_request)))
        except ProjectWatchlistItemNotFoundError as exc:
            return helpers.error(status_code=404, code="project_watchlist_item_not_found", message=str(exc))

    @router.post("/api/v1/projects/interactions")
    def record_project_interaction(http_request: Request, request: InteractionRequest):
        return helpers.success({"event": services.project_service_factory().record_interaction(_with_user_id(request, http_request))})

    @router.get("/api/v1/projects/evolution/proposals")
    def list_project_evolution_proposals():
        return helpers.success(services.project_service_factory().list_evolution_proposals())

    @router.get("/api/v1/projects/{project_id}")
    def get_project(project_id: str):
        try:
            return helpers.success(services.project_service_factory().get_project(project_id))
        except ProjectNotFoundError as exc:
            return helpers.error(status_code=404, code="project_not_found", message=str(exc))

    return router


def _actor_user_id(request: Request) -> str:
    return get_actor_context(request).actor_id or "anonymous"


def _with_user_id(payload, request: Request):
    return payload.model_copy(update={"user_id": _actor_user_id(request)})


def _with_created_by(payload, request: Request):
    return payload.model_copy(update={"created_by": _actor_user_id(request)})
