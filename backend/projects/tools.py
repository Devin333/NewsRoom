from __future__ import annotations

from backend.projects.dto import (
    PageInfo,
    ProjectToolView,
    ToolCompareResult,
    ToolRecommendRequest,
    ToolRecommendResult,
    ToolSearchQuery,
    ToolSearchResult,
    dataset_meta,
)
from backend.projects.enums import IntegrationDifficulty
from backend.projects.models import ProjectDataset, ProjectToolProfile
from backend.projects.view_models import project_card_view


DIFFICULTY_ORDER = {
    IntegrationDifficulty.LOW: 1,
    IntegrationDifficulty.MEDIUM: 2,
    IntegrationDifficulty.HIGH: 3,
}


class ProjectToolsService:
    def search(self, dataset: ProjectDataset, query: ToolSearchQuery) -> ToolSearchResult:
        views = [self._view(dataset, profile) for profile in dataset.tool_profiles]
        filtered = [view for view in views if self._matches(view, query)]
        filtered.sort(key=lambda view: _tool_sort_score(view), reverse=True)
        page, items = _paginate(filtered, page=query.page, page_size=query.limit or query.page_size)
        return ToolSearchResult(tools=items, page=page, meta=dataset_meta(dataset))

    def get(self, dataset: ProjectDataset, project_id: str) -> ProjectToolView | None:
        for profile in dataset.tool_profiles:
            if profile.project_id == project_id:
                return self._view(dataset, profile)
        return None

    def compare(self, dataset: ProjectDataset, project_ids: list[str]) -> ToolCompareResult:
        requested = {project_id for project_id in project_ids if project_id}
        tools = [self._view(dataset, profile) for profile in dataset.tool_profiles if profile.project_id in requested]
        matrix = [
            {
                "project_id": tool.project.id,
                "name": tool.project.name,
                "tool_type": tool.profile.tool_type,
                "difficulty": tool.profile.integration_difficulty.value,
                "local_deployable": tool.profile.local_deployable,
                "has_api": tool.profile.has_api,
                "has_cli": tool.profile.has_cli,
                "has_python_sdk": tool.profile.has_python_sdk,
                "capabilities": [capability["name"] for capability in tool.capabilities],
            }
            for tool in tools
        ]
        recommendation = None
        if tools:
            best = max(tools, key=_tool_sort_score)
            recommendation = f"{best.project.name} is the strongest fit among the compared real Project Radar tools."
        return ToolCompareResult(tools=tools, matrix=matrix, recommendation=recommendation, meta=dataset_meta(dataset))

    def recommend(self, dataset: ProjectDataset, request: ToolRecommendRequest) -> ToolRecommendResult:
        request_text = " ".join(
            item
            for item in [
                request.problem,
                request.target_module,
                request.input_type,
                request.output_type,
                request.deployment,
            ]
            if item
        ).casefold()
        candidates = [self._view(dataset, profile) for profile in dataset.tool_profiles]
        if request.max_difficulty is not None:
            candidates = [
                tool
                for tool in candidates
                if DIFFICULTY_ORDER[tool.profile.integration_difficulty] <= DIFFICULTY_ORDER[request.max_difficulty]
            ]
        scored = sorted(
            candidates,
            key=lambda tool: _recommend_score(tool, request_text, request),
            reverse=True,
        )[: max(1, request.limit)]
        reasoning = [
            f"{tool.project.name}: {tool.fit_reason or 'matched by capability, deployment, and source confidence.'}"
            for tool in scored
        ]
        return ToolRecommendResult(tools=scored, reasoning=reasoning, meta=dataset_meta(dataset))

    def _view(self, dataset: ProjectDataset, profile: ProjectToolProfile) -> ProjectToolView:
        project = next(project for project in dataset.projects if project.id == profile.project_id)
        capabilities = [capability.to_dict() for capability in dataset.capabilities if capability.project_id == project.id]
        reason = _fit_reason(profile, capabilities)
        return ProjectToolView(
            project=project_card_view(project, dataset),
            profile=profile,
            capabilities=capabilities,
            fit_reason=reason,
        )

    def _matches(self, view: ProjectToolView, query: ToolSearchQuery) -> bool:
        haystack = " ".join(
            [
                view.project.name,
                view.project.description or "",
                view.profile.tool_type,
                " ".join(view.project.tags),
                " ".join(view.profile.target_modules),
                " ".join(view.profile.input_types),
                " ".join(view.profile.output_types),
                " ".join(capability.get("description", "") for capability in view.capabilities),
            ]
        ).casefold()
        if query.q and query.q.casefold() not in haystack:
            return False
        if query.category and query.category.casefold() not in haystack:
            return False
        if query.use_case and query.use_case.casefold() not in haystack:
            return False
        if query.input_type and query.input_type.casefold() not in {item.casefold() for item in view.profile.input_types}:
            return False
        if query.output_type and query.output_type.casefold() not in {item.casefold() for item in view.profile.output_types}:
            return False
        if query.difficulty and query.difficulty != view.profile.integration_difficulty.value:
            return False
        if query.has_api is not None and bool(view.profile.has_api) != query.has_api:
            return False
        if query.has_cli is not None and bool(view.profile.has_cli) != query.has_cli:
            return False
        if query.has_python_sdk is not None and bool(view.profile.has_python_sdk) != query.has_python_sdk:
            return False
        if query.has_docker is not None and bool(view.profile.has_docker) != query.has_docker:
            return False
        return True


def _tool_sort_score(view: ProjectToolView) -> float:
    deploy_score = 0.2 if view.profile.local_deployable else 0.0
    api_score = 0.15 if view.profile.has_api else 0.0
    cli_score = 0.10 if view.profile.has_cli else 0.0
    sdk_score = 0.10 if view.profile.has_python_sdk else 0.0
    confidence = view.project.source_confidence * 0.30
    capability_score = min(1.0, len(view.capabilities) / 4) * 0.15
    return deploy_score + api_score + cli_score + sdk_score + confidence + capability_score


def _recommend_score(view: ProjectToolView, request_text: str, request: ToolRecommendRequest) -> float:
    haystack = " ".join(
        [
            view.project.name,
            view.project.description or "",
            view.profile.tool_type,
            " ".join(view.profile.target_modules),
            " ".join(capability.get("name", "") for capability in view.capabilities),
            " ".join(capability.get("description", "") for capability in view.capabilities),
        ]
    ).casefold()
    overlap = sum(1 for token in set(request_text.split()) if len(token) > 2 and token in haystack)
    score = _tool_sort_score(view) + min(0.4, overlap * 0.05)
    if request.target_module and request.target_module.casefold() in {item.casefold() for item in view.profile.target_modules}:
        score += 0.20
    if request.input_type and request.input_type.casefold() in {item.casefold() for item in view.profile.input_types}:
        score += 0.12
    if request.output_type and request.output_type.casefold() in {item.casefold() for item in view.profile.output_types}:
        score += 0.12
    if request.deployment and request.deployment.casefold() in {"local", "self_hosted"} and view.profile.local_deployable:
        score += 0.12
    return score


def _fit_reason(profile: ProjectToolProfile, capabilities: list[dict]) -> str:
    parts = [profile.tool_type.replace("_", " ")]
    if profile.local_deployable:
        parts.append("local deployable")
    if profile.has_api:
        parts.append("API ready")
    if profile.has_cli:
        parts.append("CLI ready")
    if capabilities:
        parts.append(f"{len(capabilities)} derived capabilities")
    return ", ".join(parts)


def _paginate(items: list[ProjectToolView], *, page: int, page_size: int) -> tuple[PageInfo, list[ProjectToolView]]:
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
