from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from business.foundation import PrimitiveModel
from business.projects.enums import CollectionType, IntegrationDifficulty
from business.projects.models import (
    LabSession,
    ModuleCase,
    Project,
    ProjectCollection,
    ProjectDataset,
    ProjectToolProfile,
    WatchlistItem,
)


class PageInfo(PrimitiveModel):
    page: int = 1
    page_size: int = 24
    total: int = 0
    has_next: bool = False
    next_cursor: str | None = None


class DatasetMeta(PrimitiveModel):
    source: Literal["backend", "artifact", "none"] = "none"
    source_run_id: str | None = None
    generated_at: str | None = None
    data_state: Literal["ready", "partial", "empty"] = "empty"
    notices: list[str] = Field(default_factory=list)


class ProjectMetricView(PrimitiveModel):
    label: str
    value: str | int | float
    hint: str | None = None


class ProjectListQuery(PrimitiveModel):
    q: str | None = None
    category: str | None = None
    tag: str | None = None
    source: str | None = None
    difficulty: str | None = None
    business_domain: str | None = None
    module_type: str | None = None
    project_type: str | None = None
    sort: str = "hot"
    page: int = 1
    page_size: int = 24
    limit: int | None = None


class ProjectCardView(PrimitiveModel):
    id: str
    slug: str
    name: str
    tagline: str | None = None
    description: str | None = None
    canonical_url: str | None = None
    website_url: str | None = None
    github_url: str | None = None
    docs_url: str | None = None
    demo_url: str | None = None
    project_type: str
    category: str | None = None
    tags: list[str] = Field(default_factory=list)
    source_confidence: float
    hot_score: float | None = None
    rising_score: float | None = None
    rank: int | None = None
    rank_reason: str | None = None
    metric_summary: dict[str, Any] = Field(default_factory=dict)
    capability_count: int = 0
    case_count: int = 0
    source_count: int = 0
    updated_at: str | None = None


class ProjectListResult(PrimitiveModel):
    items: list[ProjectCardView] = Field(default_factory=list)
    page: PageInfo = Field(default_factory=PageInfo)
    meta: DatasetMeta = Field(default_factory=DatasetMeta)
    metrics: list[ProjectMetricView] = Field(default_factory=list)


class ProjectsHomeResult(PrimitiveModel):
    hot: list[ProjectCardView] = Field(default_factory=list)
    rising: list[ProjectCardView] = Field(default_factory=list)
    tools: list[ProjectCardView] = Field(default_factory=list)
    cases: list[dict[str, Any]] = Field(default_factory=list)
    collections: list[dict[str, Any]] = Field(default_factory=list)
    watchlist: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    meta: DatasetMeta = Field(default_factory=DatasetMeta)
    metrics: list[ProjectMetricView] = Field(default_factory=list)


class RankedProject(PrimitiveModel):
    project: Project
    rank: int
    score: float
    reason: str
    factors: dict[str, float] = Field(default_factory=dict)


class ToolSearchQuery(ProjectListQuery):
    use_case: str | None = None
    input_type: str | None = None
    output_type: str | None = None
    deployment: str | None = None
    has_api: bool | None = None
    has_cli: bool | None = None
    has_python_sdk: bool | None = None
    has_docker: bool | None = None


class ProjectToolView(PrimitiveModel):
    project: ProjectCardView
    profile: ProjectToolProfile
    capabilities: list[dict[str, Any]] = Field(default_factory=list)
    fit_reason: str | None = None


class ToolSearchResult(PrimitiveModel):
    tools: list[ProjectToolView] = Field(default_factory=list)
    page: PageInfo = Field(default_factory=PageInfo)
    meta: DatasetMeta = Field(default_factory=DatasetMeta)


class ToolCompareRequest(PrimitiveModel):
    project_ids: list[str] = Field(default_factory=list)


class ToolCompareResult(PrimitiveModel):
    tools: list[ProjectToolView] = Field(default_factory=list)
    matrix: list[dict[str, Any]] = Field(default_factory=list)
    recommendation: str | None = None
    meta: DatasetMeta = Field(default_factory=DatasetMeta)


class ToolRecommendRequest(PrimitiveModel):
    problem: str
    target_module: str | None = None
    input_type: str | None = None
    output_type: str | None = None
    deployment: str | None = None
    max_difficulty: IntegrationDifficulty | None = None
    limit: int = 5


class ToolRecommendResult(PrimitiveModel):
    tools: list[ProjectToolView] = Field(default_factory=list)
    reasoning: list[str] = Field(default_factory=list)
    meta: DatasetMeta = Field(default_factory=DatasetMeta)


class CaseSearchQuery(ProjectListQuery):
    pattern: str | None = None
    migration_level: str | None = None


class CaseSearchResult(PrimitiveModel):
    cases: list[ModuleCase] = Field(default_factory=list)
    page: PageInfo = Field(default_factory=PageInfo)
    meta: DatasetMeta = Field(default_factory=DatasetMeta)


class CaseExplainRequest(PrimitiveModel):
    style: Literal["plain", "technical", "migration"] = "plain"
    user_context: str | None = None


class CaseExplainResult(PrimitiveModel):
    case_id: str
    style: Literal["plain", "technical", "migration"]
    summary: str
    key_points: list[str] = Field(default_factory=list)
    component_explanations: list[dict[str, Any]] = Field(default_factory=list)
    pattern_explanations: list[dict[str, Any]] = Field(default_factory=list)
    migration_notes: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)


class CaseMapRequest(PrimitiveModel):
    user_context: str
    target_module: str | None = None
    constraints: list[str] = Field(default_factory=list)


class CaseMapResult(PrimitiveModel):
    case_id: str
    fit_score: float
    reusable_components: list[dict[str, Any]] = Field(default_factory=list)
    migration_steps: list[str] = Field(default_factory=list)
    cautions: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)


class CollectionSearchResult(PrimitiveModel):
    collections: list[ProjectCollection] = Field(default_factory=list)
    meta: DatasetMeta = Field(default_factory=DatasetMeta)


class CollectionCreateRequest(PrimitiveModel):
    title: str
    description: str
    collection_type: CollectionType = CollectionType.TOPIC
    tags: list[str] = Field(default_factory=list)
    target_audience: list[str] = Field(default_factory=list)
    learning_goals: list[str] = Field(default_factory=list)
    created_by: str | None = None


class CollectionItemCreateRequest(PrimitiveModel):
    item_type: Literal["project", "tool", "case", "pattern", "external_link"]
    item_id: str | None = None
    external_url: str | None = None
    title: str
    reason: str
    order: int | None = None
    difficulty: str | None = None
    recommended_action: str | None = None


class CollectionGenerateRequest(PrimitiveModel):
    topic: str
    project_ids: list[str] = Field(default_factory=list)
    case_ids: list[str] = Field(default_factory=list)
    collection_type: CollectionType = CollectionType.TOPIC
    created_by: str | None = None


class CollectionMutationResult(PrimitiveModel):
    collection: ProjectCollection
    meta: DatasetMeta = Field(default_factory=DatasetMeta)


class LabSessionRequest(PrimitiveModel):
    user_problem: str
    user_id: str | None = None
    business_domain: str | None = None
    module_type: str | None = None
    target_goal: str | None = None
    current_project_context: str | None = None
    selected_case_ids: list[str] = Field(default_factory=list)


class LabAnswerRequest(PrimitiveModel):
    question_id: str
    answer: Any


class LabSolutionResult(PrimitiveModel):
    session: LabSession
    solution: dict[str, Any]


class LabNodeExplainRequest(PrimitiveModel):
    node_id: str
    style: Literal["plain", "technical"] = "plain"


class LabNodeExplainResult(PrimitiveModel):
    session_id: str
    node_id: str
    title: str
    explanation: str
    related_nodes: list[dict[str, Any]] = Field(default_factory=list)


class LabSaveRequest(PrimitiveModel):
    status: Literal["saved", "adopted", "archived"] = "saved"
    note: str | None = None


class WatchlistCreateRequest(PrimitiveModel):
    project_id: str
    user_id: str | None = None
    watch_reason: str
    watch_topics: list[str] = Field(default_factory=list)
    priority: Literal["low", "medium", "high"] = "medium"
    notify_on: list[str] = Field(default_factory=list)


class WatchlistPatchRequest(PrimitiveModel):
    watch_reason: str | None = None
    watch_topics: list[str] | None = None
    priority: Literal["low", "medium", "high"] | None = None
    status: Literal["active", "paused", "archived"] | None = None
    notify_on: list[str] | None = None
    next_action: str | None = None


class WatchlistResult(PrimitiveModel):
    items: list[WatchlistItem] = Field(default_factory=list)
    meta: DatasetMeta = Field(default_factory=DatasetMeta)


class WatchlistRefreshResult(PrimitiveModel):
    item: WatchlistItem
    signals: list[dict[str, Any]] = Field(default_factory=list)
    meta: DatasetMeta = Field(default_factory=DatasetMeta)


class InteractionRequest(PrimitiveModel):
    event_type: str
    target_type: Literal["project", "tool", "case", "component", "collection", "lab_session", "solution", "watchlist"]
    target_id: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    query_text: str | None = None
    action_value: str | None = None
    signal_strength: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)


def dataset_meta(dataset: ProjectDataset) -> DatasetMeta:
    state: Literal["ready", "partial", "empty"]
    if dataset.projects:
        state = "ready"
    elif dataset.source != "none":
        state = "partial"
    else:
        state = "empty"
    return DatasetMeta(
        source=dataset.source,
        source_run_id=dataset.source_run_id,
        generated_at=dataset.generated_at.isoformat() if dataset.generated_at else None,
        data_state=state,
        notices=list(dataset.notices),
    )
