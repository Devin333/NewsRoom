from __future__ import annotations

from datetime import datetime, timezone as _tz
UTC = _tz.utc
from typing import Any
from uuid import uuid4

from business.projects.cases import ProjectCasesService
from business.projects.collections import ProjectCollectionsService
from business.projects.dto import (
    CaseExplainRequest,
    CaseMapRequest,
    CaseSearchQuery,
    CollectionCreateRequest,
    CollectionGenerateRequest,
    CollectionItemCreateRequest,
    CollectionMutationResult,
    CollectionSearchResult,
    InteractionRequest,
    LabAnswerRequest,
    LabNodeExplainRequest,
    LabNodeExplainResult,
    LabSaveRequest,
    LabSessionRequest,
    LabSolutionResult,
    PageInfo,
    ProjectListQuery,
    ProjectListResult,
    ProjectsHomeResult,
    ToolCompareRequest,
    ToolCompareResult,
    ToolRecommendRequest,
    ToolRecommendResult,
    ToolSearchQuery,
    ToolSearchResult,
    WatchlistCreateRequest,
    WatchlistPatchRequest,
    WatchlistRefreshResult,
    WatchlistResult,
    dataset_meta,
)
from business.projects.evolution import ProjectEvolutionService
from business.projects.lab import ProjectLabService
from business.projects.models import (
    LabSession,
    ModuleCase,
    ProjectCollection,
    ProjectDataset,
    ProjectSource,
    ProjectToolProfile,
    UserProjectInteractionEvent,
    stable_id,
)
from business.projects.ranking import hot_score, rank_hot_projects, rank_rising_projects, rising_score
from business.projects.repository import ProjectArtifactRepository, ProjectStateRepository
from business.projects.tools import ProjectToolsService
from business.projects.view_models import dataset_metrics, project_card_view, ranked_project_card_view
from business.projects.watchlist import ProjectWatchlistService


class ProjectDomainService:
    def __init__(
        self,
        *,
        artifact_repository: ProjectArtifactRepository | None = None,
        state_repository: ProjectStateRepository | None = None,
    ) -> None:
        self.artifact_repository = artifact_repository or ProjectArtifactRepository()
        self.state_repository = state_repository or ProjectStateRepository()
        self.tools = ProjectToolsService()
        self.cases = ProjectCasesService()
        self.collections = ProjectCollectionsService()
        self.lab = ProjectLabService(self.state_repository)
        self.watchlist = ProjectWatchlistService(self.state_repository)
        self.evolution = ProjectEvolutionService(self.state_repository)

    def dataset(self) -> ProjectDataset:
        return self.artifact_repository.load_dataset()

    def home(self, *, limit: int = 6, user_id: str | None = None) -> ProjectsHomeResult:
        dataset = self.dataset()
        state = self.state_repository.load()
        hot = rank_hot_projects(
            dataset,
            interactions=state.interaction_events,
            watchlist_items=state.watchlist_items,
            limit=limit,
        )
        rising = rank_rising_projects(
            dataset,
            interactions=state.interaction_events,
            watchlist_items=state.watchlist_items,
            limit=limit,
        )
        tools = self.tools.search(dataset, ToolSearchQuery(limit=limit)).tools
        cases = self.cases.search(dataset, CaseSearchQuery(limit=limit)).cases
        collections = self.collections.list(dataset).collections[:limit]
        watchlist = self.watchlist.list(user_id=user_id)[:limit]
        return ProjectsHomeResult(
            hot=[ranked_project_card_view(item, dataset, score_type="hot") for item in hot],
            rising=[ranked_project_card_view(item, dataset, score_type="rising") for item in rising],
            tools=[tool.project for tool in tools],
            cases=[case.to_dict() for case in cases],
            collections=[collection.to_dict() for collection in collections],
            watchlist=[item.to_dict() for item in watchlist],
            recommendations=_recommendations(dataset, cases),
            meta=dataset_meta(dataset),
            metrics=dataset_metrics(dataset),
        )

    def list_projects(self, query: ProjectListQuery) -> ProjectListResult:
        dataset = self.dataset()
        state = self.state_repository.load()
        projects = [project for project in dataset.projects if _matches_project(project, query)]
        sort = query.sort.casefold()
        if sort == "rising":
            ranked = [
                item
                for item in rank_rising_projects(dataset, interactions=state.interaction_events, watchlist_items=state.watchlist_items)
                if item.project in projects
            ]
            cards = [ranked_project_card_view(item, dataset, score_type="rising") for item in ranked]
        else:
            ranked = [
                item
                for item in rank_hot_projects(dataset, interactions=state.interaction_events, watchlist_items=state.watchlist_items)
                if item.project in projects
            ]
            if sort in {"name", "newest"}:
                ranked = _sort_ranked(ranked, sort)
            cards = [ranked_project_card_view(item, dataset, score_type="hot") for item in ranked]
        page, items = _paginate(cards, page=query.page, page_size=query.limit or query.page_size)
        return ProjectListResult(items=items, page=page, meta=dataset_meta(dataset), metrics=dataset_metrics(dataset))

    def hot(self, query: ProjectListQuery) -> ProjectListResult:
        return self.list_projects(query.model_copy(update={"sort": "hot"}))

    def rising(self, query: ProjectListQuery) -> ProjectListResult:
        return self.list_projects(query.model_copy(update={"sort": "rising"}))

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        dataset = self.dataset()
        state = self.state_repository.load()
        project = _find_project(dataset, project_id)
        if project is None:
            return None
        hot_value, hot_factors, hot_reason = hot_score(project, dataset)
        rising_value, rising_factors, rising_reason = rising_score(project, dataset)
        related_collections = [
            collection.to_dict()
            for collection in [*dataset.collections, *state.user_collections]
            if _collection_references_project(collection, project.id)
        ]
        watch_status = next(
            (item.to_dict() for item in state.watchlist_items if item.project_id == project.id and item.status != "archived"),
            None,
        )
        return {
            "project": project_card_view(
                project,
                dataset,
                hot_score=hot_value,
                rising_score=rising_value,
                rank_reason=f"{hot_reason} {rising_reason}",
            ).to_dict(),
            "sources": [source.to_dict() for source in dataset.sources if source.project_id == project.id],
            "metrics": [metric.to_dict() for metric in dataset.metric_snapshots if metric.project_id == project.id],
            "growth": [growth.to_dict() for growth in dataset.growth_snapshots if growth.project_id == project.id],
            "capabilities": [capability.to_dict() for capability in dataset.capabilities if capability.project_id == project.id],
            "tool_profile": _tool_profile_dict(dataset, project.id),
            "cases": [case.to_dict() for case in dataset.cases if case.project_id == project.id],
            "collections": related_collections,
            "watch_status": watch_status,
            "recommended_actions": _project_actions(project, bool(watch_status), related_collections),
            "ranking": {
                "hot": {"score": hot_value, "factors": hot_factors, "reason": hot_reason},
                "rising": {"score": rising_value, "factors": rising_factors, "reason": rising_reason},
            },
            "meta": dataset_meta(dataset).to_dict(),
        }

    def search_tools(self, query: ToolSearchQuery) -> ToolSearchResult:
        return self.tools.search(self.dataset(), query)

    def get_tool(self, project_id: str):
        return self.tools.get(self.dataset(), project_id)

    def compare_tools(self, request: ToolCompareRequest) -> ToolCompareResult:
        return self.tools.compare(self.dataset(), request.project_ids)

    def recommend_tools(self, request: ToolRecommendRequest) -> ToolRecommendResult:
        return self.tools.recommend(self.dataset(), request)

    def search_cases(self, query: CaseSearchQuery):
        return self.cases.search(self.dataset(), query)

    def get_case(self, case_id: str) -> ModuleCase | None:
        return self.cases.get(self.dataset(), case_id)

    def explain_case(self, case_id: str, request: CaseExplainRequest):
        return self.cases.explain(self.dataset(), case_id, request)

    def map_case_to_context(self, case_id: str, request: CaseMapRequest):
        return self.cases.map_to_context(self.dataset(), case_id, request)

    def list_collections(self) -> CollectionSearchResult:
        state = self.state_repository.load()
        return self.collections.list(self.dataset(), state.user_collections)

    def get_collection(self, slug: str) -> ProjectCollection | None:
        state = self.state_repository.load()
        return self.collections.get(self.dataset(), slug, state.user_collections)

    def create_collection(self, request: CollectionCreateRequest) -> CollectionMutationResult:
        dataset = self.dataset()
        collection: ProjectCollection | None = None

        def update(state):
            nonlocal collection
            collection = self.collections.create(dataset, state.user_collections, request)
            return state.model_copy(update={"user_collections": [*state.user_collections, collection]})

        self.state_repository.update(update)
        if collection is None:
            raise RuntimeError("collection creation failed")
        return CollectionMutationResult(collection=collection, meta=dataset_meta(dataset))

    def add_collection_item(self, collection_id: str, request: CollectionItemCreateRequest) -> CollectionMutationResult | None:
        dataset = self.dataset()
        updated: ProjectCollection | None = None

        def update_state(state):
            nonlocal updated
            editable = list(state.user_collections)
            if not any(collection.id == collection_id or collection.slug == collection_id for collection in editable):
                artifact_collection = self.collections.get(dataset, collection_id, [])
                if artifact_collection is not None:
                    editable.append(artifact_collection)
            updated = self.collections.add_item(dataset, editable, collection_id, request)
            if updated is None:
                return state
            return state.model_copy(update={"user_collections": _replace_collection(editable, updated)})

        self.state_repository.update(update_state)
        if updated is None:
            return None
        return CollectionMutationResult(collection=updated, meta=dataset_meta(dataset))

    def generate_collection(self, request: CollectionGenerateRequest) -> CollectionMutationResult:
        dataset = self.dataset()
        collection: ProjectCollection | None = None

        def update(state):
            nonlocal collection
            collection = self.collections.generate(dataset, state.user_collections, request)
            return state.model_copy(update={"user_collections": [*state.user_collections, collection]})

        self.state_repository.update(update)
        if collection is None:
            raise RuntimeError("collection generation failed")
        return CollectionMutationResult(collection=collection, meta=dataset_meta(dataset))

    def start_lab_session(self, request: LabSessionRequest) -> LabSession:
        return self.lab.start_session(self.dataset(), request)

    def get_lab_session(self, session_id: str) -> LabSession | None:
        return self.lab.get_session(session_id)

    def answer_lab_question(self, session_id: str, request: LabAnswerRequest) -> LabSession | None:
        return self.lab.answer(session_id, request)

    def generate_lab_solution(self, session_id: str) -> LabSolutionResult | None:
        return self.lab.generate_solution(self.dataset(), session_id)

    def explain_lab_node(self, session_id: str, request: LabNodeExplainRequest) -> LabNodeExplainResult | None:
        return self.lab.explain_node(session_id, request)

    def save_lab_session(self, session_id: str, request: LabSaveRequest) -> LabSession | None:
        return self.lab.save_session(session_id, request)

    def list_watchlist(self, *, user_id: str | None = None) -> WatchlistResult:
        dataset = self.dataset()
        return WatchlistResult(items=self.watchlist.list(user_id=user_id), meta=dataset_meta(dataset))

    def add_watchlist(self, request: WatchlistCreateRequest):
        return self.watchlist.add(self.dataset(), request)

    def patch_watchlist(self, item_id: str, request: WatchlistPatchRequest, *, user_id: str | None = None):
        return self.watchlist.patch(item_id, request, user_id=user_id)

    def refresh_watchlist(self, item_id: str, *, user_id: str | None = None) -> WatchlistRefreshResult | None:
        dataset = self.dataset()
        item = self.watchlist.refresh(dataset, item_id, user_id=user_id)
        if item is None:
            return None
        return WatchlistRefreshResult(
            item=item,
            signals=[signal.to_dict() for signal in item.signals],
            meta=dataset_meta(dataset),
        )

    def delete_watchlist(self, item_id: str, *, user_id: str | None = None) -> bool:
        return self.watchlist.delete(item_id, user_id=user_id)

    def record_interaction(self, request: InteractionRequest) -> UserProjectInteractionEvent:
        created_at = datetime.now(UTC)
        event = UserProjectInteractionEvent(
            id=stable_id(
                "interaction",
                request.user_id or "anonymous",
                request.event_type,
                request.target_type,
                request.target_id or "",
                request.query_text or "",
                created_at.isoformat(),
                uuid4().hex,
            ),
            user_id=request.user_id,
            session_id=request.session_id,
            event_type=request.event_type,
            target_type=request.target_type,
            target_id=request.target_id,
            query_text=request.query_text,
            action_value=request.action_value,
            signal_strength=max(0.0, min(1.0, request.signal_strength)),
            metadata=request.metadata,
            created_at=created_at,
        )
        return self.evolution.record_interaction(event)

    def list_evolution_proposals(self) -> list[dict[str, Any]]:
        return [proposal.to_dict() for proposal in self.evolution.proposals()]


def _matches_project(project, query: ProjectListQuery) -> bool:
    haystack = " ".join(
        [
            project.name,
            project.tagline or "",
            project.description or "",
            project.category or "",
            " ".join(project.tags),
            " ".join(project.suitable_for),
            " ".join(project.learnable_points),
        ]
    ).casefold()
    if query.q and query.q.casefold() not in haystack:
        return False
    if query.category and query.category.casefold() not in haystack:
        return False
    if query.tag and query.tag.casefold() not in {tag.casefold() for tag in project.tags}:
        return False
    if query.project_type and query.project_type != project.project_type.value:
        return False
    if query.source and query.source.casefold() == "github" and not project.github_url:
        return False
    return True


def _find_project(dataset: ProjectDataset, project_id: str):
    for project in dataset.projects:
        if project.id == project_id or project.slug == project_id:
            return project
    return None


def _tool_profile_dict(dataset: ProjectDataset, project_id: str) -> dict[str, Any] | None:
    for profile in dataset.tool_profiles:
        if profile.project_id == project_id:
            return profile.to_dict()
    return None


def _collection_references_project(collection: ProjectCollection, project_id: str) -> bool:
    for section in collection.sections:
        for item in section.items:
            if item.item_type in {"project", "tool"} and item.item_id == project_id:
                return True
    return False


def _replace_collection(collections: list[ProjectCollection], updated: ProjectCollection) -> list[ProjectCollection]:
    replaced = False
    result: list[ProjectCollection] = []
    for collection in collections:
        if collection.id == updated.id:
            result.append(updated)
            replaced = True
        else:
            result.append(collection)
    if not replaced:
        result.append(updated)
    return result


def _sort_ranked(items, sort: str):
    if sort == "name":
        return sorted(items, key=lambda item: item.project.name.casefold())
    if sort == "newest":
        return sorted(items, key=lambda item: item.project.created_at, reverse=True)
    return items


def _project_actions(project, watched: bool, collections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actions = [
        {
            "id": "open_sources",
            "label": "Review source evidence",
            "reason": "Verify public source references before adopting the project.",
        }
    ]
    if project.project_type.value == "tool":
        actions.append(
            {
                "id": "compare_tool",
                "label": "Compare as a tool",
                "reason": "Tool profiles can be compared against integration needs.",
            }
        )
    if not watched:
        actions.append(
            {
                "id": "add_watchlist",
                "label": "Add to watchlist",
                "reason": "Track future Project Radar metric and source changes.",
            }
        )
    if not collections:
        actions.append(
            {
                "id": "add_collection",
                "label": "Add to collection",
                "reason": "Group this project with related research and module cases.",
            }
        )
    return actions


def _paginate(items, *, page: int, page_size: int) -> tuple[PageInfo, list[Any]]:
    resolved_page = max(1, int(page or 1))
    resolved_page_size = max(1, min(100, int(page_size or 24)))
    start = (resolved_page - 1) * resolved_page_size
    end = start + resolved_page_size
    return (
        PageInfo(
            page=resolved_page,
            page_size=resolved_page_size,
            total=len(items),
            has_next=end < len(items),
            next_cursor=str(resolved_page + 1) if end < len(items) else None,
        ),
        items[start:end],
    )


def _recommendations(dataset: ProjectDataset, cases: list[ModuleCase]) -> list[dict[str, Any]]:
    if not dataset.projects:
        return []
    recommendations: list[dict[str, Any]] = []
    if cases:
        recommendations.append(
            {
                "type": "lab",
                "title": "Start a Lab session from similar cases",
                "reason": f"{len(cases)} real-derived cases are available for solution design.",
            }
        )
    if dataset.tool_profiles:
        recommendations.append(
            {
                "type": "tools",
                "title": "Compare derived tools",
                "reason": f"{len(dataset.tool_profiles)} tool profiles were derived from Project Radar.",
            }
        )
    return recommendations
