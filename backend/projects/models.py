from __future__ import annotations

from datetime import datetime, timezone as _tz
UTC = _tz.utc
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from backend.foundation import PrimitiveModel, build_stable_id, slugify
from backend.projects.enums import (
    CollectionType,
    IntegrationDifficulty,
    LabSessionStatus,
    ProjectSourceType,
    ProjectStatus,
    ProjectType,
    ReuseLevel,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class Project(PrimitiveModel):
    id: str
    name: str
    slug: str = ""
    tagline: str | None = None
    description: str | None = None
    canonical_url: str | None = None
    website_url: str | None = None
    github_url: str | None = None
    docs_url: str | None = None
    demo_url: str | None = None
    project_type: ProjectType = ProjectType.PROJECT
    category: str | None = None
    tags: list[str] = Field(default_factory=list)
    status: ProjectStatus = ProjectStatus.ACTIVE
    source_confidence: float = 0.5
    ai_summary: str | None = None
    why_it_matters: str | None = None
    suitable_for: list[str] = Field(default_factory=list)
    learnable_points: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id", "name")
    @classmethod
    def _required_text(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("project id and name are required")
        return text

    @field_validator("source_confidence")
    @classmethod
    def _bounded_confidence(cls, value: float) -> float:
        return max(0.0, min(float(value), 1.0))

    @model_validator(mode="after")
    def _normalize(self) -> "Project":
        object.__setattr__(self, "slug", self.slug or slugify(self.name))
        object.__setattr__(self, "tags", _unique_texts(self.tags))
        object.__setattr__(self, "suitable_for", _unique_texts(self.suitable_for))
        object.__setattr__(self, "learnable_points", _unique_texts(self.learnable_points))
        return self


class ProjectSource(PrimitiveModel):
    id: str
    project_id: str
    source_name: str
    source_type: ProjectSourceType
    source_url: str
    external_id: str | None = None
    raw_title: str | None = None
    raw_description: str | None = None
    raw_metadata: dict[str, Any] = Field(default_factory=dict)
    fetched_at: datetime = Field(default_factory=utc_now)

    @field_validator("raw_metadata")
    @classmethod
    def _sanitize_raw_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _sanitize_metadata(value)


class ProjectMetricSnapshot(PrimitiveModel):
    id: str
    project_id: str
    snapshot_at: datetime = Field(default_factory=utc_now)
    github_stars: int | None = None
    github_forks: int | None = None
    github_watchers: int | None = None
    github_open_issues: int | None = None
    product_hunt_votes: int | None = None
    hn_points: int | None = None
    hn_comments: int | None = None
    reddit_score: int | None = None
    reddit_comments: int | None = None
    internal_views: int = 0
    internal_saves: int = 0
    internal_watches: int = 0
    internal_lab_uses: int = 0
    source_mentions: int = 0
    release_count: int = 0
    quality_score: float | None = None
    activity_score: float | None = None
    evidence_score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectGrowthSnapshot(PrimitiveModel):
    id: str
    project_id: str
    window: Literal["7d", "30d", "90d"] = "7d"
    stars_start: int | None = None
    stars_end: int | None = None
    stars_delta: int | None = None
    votes_delta: int | None = None
    mentions_delta: int | None = None
    internal_watch_delta: int = 0
    release_count: int = 0
    computed_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectCapability(PrimitiveModel):
    id: str
    project_id: str
    name: str
    capability_type: str
    description: str
    input_desc: str | None = None
    output_desc: str | None = None
    reusable_level: ReuseLevel = ReuseLevel.MEDIUM
    difficulty: IntegrationDifficulty = IntegrationDifficulty.MEDIUM
    target_modules: list[str] = Field(default_factory=list)


class ProjectToolProfile(PrimitiveModel):
    project_id: str
    tool_type: str
    input_types: list[str] = Field(default_factory=list)
    output_types: list[str] = Field(default_factory=list)
    is_open_source: bool | None = None
    license: str | None = None
    local_deployable: bool | None = None
    has_api: bool | None = None
    has_cli: bool | None = None
    has_python_sdk: bool | None = None
    has_docker: bool | None = None
    integration_difficulty: IntegrationDifficulty = IntegrationDifficulty.MEDIUM
    recommended_integration: Literal["direct_use", "wrap_as_service", "reference_only"] | None = None
    target_modules: list[str] = Field(default_factory=list)
    setup_commands: list[str] = Field(default_factory=list)
    usage_example: str | None = None
    known_limits: list[str] = Field(default_factory=list)
    experiment_status: Literal["untested", "runnable", "failed", "adopted"] = "untested"


class CaseComponent(PrimitiveModel):
    id: str
    case_id: str
    name: str
    component_type: str
    responsibility: str
    input_desc: str | None = None
    output_desc: str | None = None
    dependency_desc: str | None = None
    plain_explanation: str
    migration_advice: str | None = None


class DesignPattern(PrimitiveModel):
    id: str
    case_id: str
    name: str
    pattern_type: str
    explanation: str
    when_to_use: str
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)


class DataFlowStep(PrimitiveModel):
    id: str
    case_id: str
    order: int
    title: str
    description: str


class ModuleCase(PrimitiveModel):
    id: str
    project_id: str
    title: str
    business_domain: str
    module_type: str
    problem: str
    design_summary: str
    plain_explanation: str
    design_logic: str
    components: list[CaseComponent] = Field(default_factory=list)
    patterns: list[DesignPattern] = Field(default_factory=list)
    data_flow: list[DataFlowStep] = Field(default_factory=list)
    migration_level: ReuseLevel = ReuseLevel.MEDIUM
    reference_value: ReuseLevel = ReuseLevel.MEDIUM
    difficulty: IntegrationDifficulty = IntegrationDifficulty.MEDIUM
    suitable_for: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    status: Literal["draft", "reviewed", "published", "archived"] = "published"


class CollectionItem(PrimitiveModel):
    id: str
    collection_id: str
    item_type: Literal["project", "tool", "case", "pattern", "external_link"]
    item_id: str | None = None
    external_url: str | None = None
    title: str
    reason: str
    order: int
    difficulty: str | None = None
    recommended_action: str | None = None


class CollectionSection(PrimitiveModel):
    id: str
    title: str
    description: str | None = None
    order: int
    items: list[CollectionItem] = Field(default_factory=list)


class ProjectCollection(PrimitiveModel):
    id: str
    slug: str
    title: str
    subtitle: str | None = None
    description: str
    collection_type: CollectionType
    tags: list[str] = Field(default_factory=list)
    target_audience: list[str] = Field(default_factory=list)
    learning_goals: list[str] = Field(default_factory=list)
    sections: list[CollectionSection] = Field(default_factory=list)
    item_count: int = 0
    curator_note: str | None = None
    status: Literal["draft", "published", "archived"] = "published"
    created_by: str | None = None
    updated_at: datetime = Field(default_factory=utc_now)


class WatchSignal(PrimitiveModel):
    id: str
    project_id: str
    signal_type: str
    title: str
    summary: str
    source_url: str | None = None
    severity: Literal["low", "medium", "high"] = "medium"
    occurred_at: datetime = Field(default_factory=utc_now)
    detected_at: datetime = Field(default_factory=utc_now)


class WatchlistItem(PrimitiveModel):
    id: str
    user_id: str
    project_id: str
    watch_reason: str
    watch_topics: list[str] = Field(default_factory=list)
    priority: Literal["low", "medium", "high"] = "medium"
    status: Literal["active", "paused", "archived"] = "active"
    notify_on: list[str] = Field(default_factory=lambda: ["release", "docs_change", "hot_score"])
    last_checked_at: datetime | None = None
    last_change_summary: str | None = None
    next_action: str | None = None
    signals: list[WatchSignal] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class LabGraphNode(PrimitiveModel):
    id: str
    node_type: Literal["user_problem", "scenario", "module", "case", "pattern", "component", "question", "solution", "feedback"]
    title: str
    payload: dict[str, Any] = Field(default_factory=dict)
    weight: float = 1.0


class LabGraphEdge(PrimitiveModel):
    source_id: str
    target_id: str
    relation_type: str
    weight: float = 1.0
    reason: str | None = None


class LabGraphState(PrimitiveModel):
    session_id: str
    nodes: list[LabGraphNode] = Field(default_factory=list)
    edges: list[LabGraphEdge] = Field(default_factory=list)
    focused_node_ids: list[str] = Field(default_factory=list)
    hidden_node_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LabQuestion(PrimitiveModel):
    id: str
    session_id: str
    question: str
    question_type: Literal["single_choice", "multi_choice", "priority_rank", "scale", "free_text", "confirm"]
    options: list[dict[str, str]] = Field(default_factory=list)
    purpose: str
    required: bool = True
    answered_value: Any | None = None


class LabSolution(PrimitiveModel):
    id: str
    session_id: str
    title: str
    markdown: str
    solution_json: dict[str, Any] = Field(default_factory=dict)
    review_notes: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class LabSession(PrimitiveModel):
    id: str
    user_id: str | None = None
    user_problem: str
    business_domain: str | None = None
    module_type: str | None = None
    target_goal: str | None = None
    current_project_context: str | None = None
    requirement_profile: dict[str, Any] = Field(default_factory=dict)
    selected_case_ids: list[str] = Field(default_factory=list)
    graph_state: LabGraphState
    questions: list[LabQuestion] = Field(default_factory=list)
    current_stage: str = "clarifying_requirements"
    next_action: str = "answer_question"
    can_generate_solution: bool = False
    unanswered_question_ids: list[str] = Field(default_factory=list)
    generated_solution: str | None = None
    solution_json: dict[str, Any] | None = None
    status: LabSessionStatus = LabSessionStatus.ACTIVE
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class UserProjectInteractionEvent(PrimitiveModel):
    id: str
    user_id: str | None = None
    session_id: str | None = None
    event_type: str
    target_type: Literal["project", "tool", "case", "component", "collection", "lab_session", "solution", "watchlist"]
    target_id: str | None = None
    query_text: str | None = None
    action_value: str | None = None
    signal_strength: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class EvolutionProposal(PrimitiveModel):
    id: str
    proposal_type: Literal[
        "ranking_weight_update",
        "question_template_update",
        "explanation_template_update",
        "case_tag_update",
        "collection_recommendation_update",
        "solution_template_update",
    ]
    title: str
    summary: str
    evidence: list[str] = Field(default_factory=list)
    proposed_change: dict[str, Any]
    expected_impact: str
    risk_level: Literal["low", "medium", "high"] = "low"
    status: Literal["draft", "reviewing", "approved", "rejected", "applied"] = "draft"
    created_at: datetime = Field(default_factory=utc_now)


class ProjectDataset(PrimitiveModel):
    projects: list[Project] = Field(default_factory=list)
    sources: list[ProjectSource] = Field(default_factory=list)
    metric_snapshots: list[ProjectMetricSnapshot] = Field(default_factory=list)
    growth_snapshots: list[ProjectGrowthSnapshot] = Field(default_factory=list)
    capabilities: list[ProjectCapability] = Field(default_factory=list)
    tool_profiles: list[ProjectToolProfile] = Field(default_factory=list)
    cases: list[ModuleCase] = Field(default_factory=list)
    collections: list[ProjectCollection] = Field(default_factory=list)
    source: Literal["backend", "artifact", "none"] = "none"
    source_run_id: str | None = None
    generated_at: datetime | None = None
    notices: list[str] = Field(default_factory=list)


def stable_id(prefix: str, *parts: Any) -> str:
    return build_stable_id(prefix, *parts)


def _unique_texts(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _sanitize_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_sensitive_metadata_key(key_text):
                continue
            result[key_text] = _sanitize_metadata(item)
        return result
    if isinstance(value, list):
        return [_sanitize_metadata(item) for item in value]
    return value


def _is_sensitive_metadata_key(key: str) -> bool:
    normalized = "".join(ch for ch in key.casefold() if ch.isalnum())
    exact = {"rawpayload", "rawcontent", "rawhtml", "fulltext", "authorization", "cookie", "setcookie"}
    fragments = ("secret", "token", "apikey", "credential", "password", "passwd", "sessionid")
    return normalized in exact or any(fragment in normalized for fragment in fragments)
