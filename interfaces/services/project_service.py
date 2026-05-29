from __future__ import annotations

from pathlib import Path
from typing import Any

from business.projects import (
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
    ProjectArtifactRepository,
    ProjectDomainService,
    ProjectListQuery,
    ProjectStateRepository,
    ToolCompareRequest,
    ToolRecommendRequest,
    ToolSearchQuery,
    WatchlistCreateRequest,
    WatchlistPatchRequest,
)
from business.projects.bridge import ProjectRadarBridge


class ProjectNotFoundError(LookupError):
    pass


class ProjectCaseNotFoundError(LookupError):
    pass


class ProjectCollectionNotFoundError(LookupError):
    pass


class ProjectLabNodeNotFoundError(LookupError):
    pass


class ProjectLabSessionNotFoundError(LookupError):
    pass


class ProjectWatchlistItemNotFoundError(LookupError):
    pass


class ProjectApplicationService:
    def __init__(
        self,
        *,
        runs_root: str | Path | None = None,
        state_path: str | Path | None = None,
        domain_service: ProjectDomainService | None = None,
    ) -> None:
        if domain_service is not None:
            self.domain = domain_service
        else:
            artifact_repository = ProjectArtifactRepository(
                runs_root=runs_root,
                bridge=ProjectRadarBridge(),
            )
            state_repository = ProjectStateRepository(state_path)
            self.domain = ProjectDomainService(
                artifact_repository=artifact_repository,
                state_repository=state_repository,
            )

    def get_home(self, *, limit: int = 6, user_id: str | None = None) -> dict[str, Any]:
        return self.domain.home(limit=limit, user_id=user_id).to_dict()

    def list_projects(self, query: ProjectListQuery) -> dict[str, Any]:
        return self.domain.list_projects(query).to_dict()

    def list_hot(self, query: ProjectListQuery) -> dict[str, Any]:
        return self.domain.hot(query).to_dict()

    def list_rising(self, query: ProjectListQuery) -> dict[str, Any]:
        return self.domain.rising(query).to_dict()

    def get_project(self, project_id: str) -> dict[str, Any]:
        result = self.domain.get_project(project_id)
        if result is None:
            raise ProjectNotFoundError(f"project not found: {project_id}")
        return result

    def search_tools(self, query: ToolSearchQuery) -> dict[str, Any]:
        return self.domain.search_tools(query).to_dict()

    def get_tool_detail(self, project_id: str) -> dict[str, Any]:
        result = self.domain.get_tool(project_id)
        if result is None:
            raise ProjectNotFoundError(f"project tool not found: {project_id}")
        return result.to_dict()

    def compare_tools(self, request: ToolCompareRequest) -> dict[str, Any]:
        return self.domain.compare_tools(request).to_dict()

    def recommend_tools(self, request: ToolRecommendRequest) -> dict[str, Any]:
        return self.domain.recommend_tools(request).to_dict()

    def search_cases(self, query: CaseSearchQuery) -> dict[str, Any]:
        return self.domain.search_cases(query).to_dict()

    def get_case_detail(self, case_id: str) -> dict[str, Any]:
        result = self.domain.get_case(case_id)
        if result is None:
            raise ProjectCaseNotFoundError(f"project case not found: {case_id}")
        return result.to_dict()

    def explain_case(self, case_id: str, request: CaseExplainRequest) -> dict[str, Any]:
        result = self.domain.explain_case(case_id, request)
        if result is None:
            raise ProjectCaseNotFoundError(f"project case not found: {case_id}")
        return result.to_dict()

    def map_case_to_context(self, case_id: str, request: CaseMapRequest) -> dict[str, Any]:
        result = self.domain.map_case_to_context(case_id, request)
        if result is None:
            raise ProjectCaseNotFoundError(f"project case not found: {case_id}")
        return result.to_dict()

    def list_collections(self) -> dict[str, Any]:
        return self.domain.list_collections().to_dict()

    def get_collection(self, slug: str) -> dict[str, Any]:
        result = self.domain.get_collection(slug)
        if result is None:
            raise ProjectCollectionNotFoundError(f"project collection not found: {slug}")
        return result.to_dict()

    def create_collection(self, request: CollectionCreateRequest) -> dict[str, Any]:
        return self.domain.create_collection(request).to_dict()

    def add_collection_item(self, collection_id: str, request: CollectionItemCreateRequest) -> dict[str, Any]:
        result = self.domain.add_collection_item(collection_id, request)
        if result is None:
            raise ProjectCollectionNotFoundError(f"project collection not found: {collection_id}")
        return result.to_dict()

    def generate_collection(self, request: CollectionGenerateRequest) -> dict[str, Any]:
        return self.domain.generate_collection(request).to_dict()

    def start_lab_session(self, request: LabSessionRequest) -> dict[str, Any]:
        return self.domain.start_lab_session(request).to_dict()

    def get_lab_session(self, session_id: str) -> dict[str, Any]:
        result = self.domain.get_lab_session(session_id)
        if result is None:
            raise ProjectLabSessionNotFoundError(f"project lab session not found: {session_id}")
        return result.to_dict()

    def answer_lab_question(self, session_id: str, request: LabAnswerRequest) -> dict[str, Any]:
        result = self.domain.answer_lab_question(session_id, request)
        if result is None:
            raise ProjectLabSessionNotFoundError(f"project lab session not found: {session_id}")
        return result.to_dict()

    def generate_lab_solution(self, session_id: str) -> dict[str, Any]:
        result = self.domain.generate_lab_solution(session_id)
        if result is None:
            raise ProjectLabSessionNotFoundError(f"project lab session not found: {session_id}")
        return result.to_dict()

    def explain_lab_node(self, session_id: str, request: LabNodeExplainRequest) -> dict[str, Any]:
        result = self.domain.explain_lab_node(session_id, request)
        if result is None:
            raise ProjectLabNodeNotFoundError(f"project lab node not found: {session_id}/{request.node_id}")
        return result.to_dict()

    def save_lab_session(self, session_id: str, request: LabSaveRequest) -> dict[str, Any]:
        result = self.domain.save_lab_session(session_id, request)
        if result is None:
            raise ProjectLabSessionNotFoundError(f"project lab session not found: {session_id}")
        return result.to_dict()

    def list_watchlist(self, *, user_id: str | None = None) -> dict[str, Any]:
        return self.domain.list_watchlist(user_id=user_id).to_dict()

    def add_watchlist(self, request: WatchlistCreateRequest) -> dict[str, Any]:
        return self.domain.add_watchlist(request).to_dict()

    def patch_watchlist(self, item_id: str, request: WatchlistPatchRequest, *, user_id: str | None = None) -> dict[str, Any]:
        result = self.domain.patch_watchlist(item_id, request, user_id=user_id)
        if result is None:
            raise ProjectWatchlistItemNotFoundError(f"project watchlist item not found: {item_id}")
        return result.to_dict()

    def refresh_watchlist(self, item_id: str, *, user_id: str | None = None) -> dict[str, Any]:
        result = self.domain.refresh_watchlist(item_id, user_id=user_id)
        if result is None:
            raise ProjectWatchlistItemNotFoundError(f"project watchlist item not found: {item_id}")
        return result.to_dict()

    def delete_watchlist(self, item_id: str, *, user_id: str | None = None) -> dict[str, Any]:
        deleted = self.domain.delete_watchlist(item_id, user_id=user_id)
        if not deleted:
            raise ProjectWatchlistItemNotFoundError(f"project watchlist item not found: {item_id}")
        return {"deleted": True, "item_id": item_id}

    def record_interaction(self, request: InteractionRequest) -> dict[str, Any]:
        return self.domain.record_interaction(request).to_dict()

    def list_evolution_proposals(self) -> dict[str, Any]:
        return {"proposals": self.domain.list_evolution_proposals()}


# Backward-compatible alias for early tests and callers.
ProjectsApplicationService = ProjectApplicationService


__all__ = [
    "CaseExplainRequest",
    "CaseMapRequest",
    "CaseSearchQuery",
    "CollectionCreateRequest",
    "CollectionGenerateRequest",
    "CollectionItemCreateRequest",
    "InteractionRequest",
    "LabAnswerRequest",
    "LabNodeExplainRequest",
    "LabSaveRequest",
    "LabSessionRequest",
    "ProjectApplicationService",
    "ProjectCaseNotFoundError",
    "ProjectCollectionNotFoundError",
    "ProjectLabNodeNotFoundError",
    "ProjectLabSessionNotFoundError",
    "ProjectListQuery",
    "ProjectNotFoundError",
    "ProjectsApplicationService",
    "ProjectWatchlistItemNotFoundError",
    "ToolCompareRequest",
    "ToolRecommendRequest",
    "ToolSearchQuery",
    "WatchlistCreateRequest",
    "WatchlistPatchRequest",
]
