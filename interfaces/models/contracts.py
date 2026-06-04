from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field



SCHEMA_VERSION = "1.0"
RunStatus = Literal[
    "accepted",
    "queued",
    "running",
    "paused",
    "waiting_for_human",
    "succeeded",
    "failed",
    "blocked",
    "cancelled",
    "budget_exceeded",
]
ReportStatus = Literal[
    "draft",
    "ready",
    "needs_review",
    "published",
    "blocked",
    "failed",
]


class ApiMeta(BaseModel):
    request_id: str
    schema_version: str = SCHEMA_VERSION


class PageRequest(BaseModel):
    limit: int = Field(default=20, ge=1)
    cursor: str | None = None
    offset: int | None = Field(default=None, ge=0)


class ApiError(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False
    user_action_required: bool = False
    request_id: str | None = None


class ApiResponse(BaseModel):
    success: bool
    data: dict[str, Any] | None = None
    error: ApiError | None = None
    request_id: str
    schema_version: str = SCHEMA_VERSION


class ArtifactRef(BaseModel):
    artifact_id: str
    path: str
    run_id: str | None = None
    artifact_type: str | None = None
    content_type: str | None = None
    redacted: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunResponse(BaseModel):
    run_id: str | None = None
    task_id: str | None = None
    status: RunStatus
    task_status: str | None = None
    run_status: str | None = None
    report_status: str | None = None
    report_id: str | None = None
    manifest_ref: ArtifactRef | None = None
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)
    message: str | None = None


class RunListItem(BaseModel):
    run_id: str
    workflow_id: str | None = None
    workflow_version: str | None = None
    profile: str | None = None
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    report_id: str | None = None
    artifact_dir: str | None = None


class RunDetail(RunListItem):
    output_preview: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class RunEventView(BaseModel):
    event_id: str | None = None
    event_type: str
    step_id: str | None = None
    created_at: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class RunOperationRequest(BaseModel):
    reason: str | None = None
    actor_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunRerunFromStepRequest(RunOperationRequest):
    step_id: str = Field(min_length=1)


class RunResumeWithPatchRequest(RunOperationRequest):
    patch: dict[str, Any] = Field(default_factory=dict)


class RunSkipStepRequest(RunOperationRequest):
    step_id: str = Field(min_length=1)


class RunMarkBlockedResolvedRequest(RunOperationRequest):
    resolution_type: str = Field(default="manual", min_length=1)
    resolved_by: str | None = None


class ReportSummary(BaseModel):
    report_id: str
    run_id: str
    status: str
    summary: str | None = None
    title: str | None = None
    created_at: datetime | None = None
    published_at: datetime | None = None
    quality_score: float | None = None
    citation_coverage_score: float | None = None
    source_count: int | None = None
    evidence_count: int | None = None
    manifest_path: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReportDetail(ReportSummary):
    report_json: dict[str, Any] | None = None
    report_markdown: str | None = None


class ReportActionRequest(BaseModel):
    requested_by: str | None = None
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemorySearchRequest(BaseModel):
    query: str
    collection: str = "report_sections"
    limit: int = Field(default=5, ge=1)
    filters: dict[str, Any] = Field(default_factory=dict)


class MemorySearchMatch(BaseModel):
    document_id: str
    collection: str | None = None
    score: float | None = None
    text: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemorySearchResponse(BaseModel):
    collection: str
    query: str
    filters: dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(default=5, ge=1)
    result_count: int
    results: list[MemorySearchMatch] = Field(default_factory=list)


class MemoryReindexRequest(BaseModel):
    run_id: str
    topic: str | None = None


class MCPToolCallRequest(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


class MCPResourceReadRequest(BaseModel):
    uri: str = Field(min_length=1)


class MCPPromptGetRequest(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


class SourceHealthView(BaseModel):
    source_id: str
    status: str
    source_name: str | None = None
    url: str | None = None
    consecutive_failures: int = 0
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    cooldown_until: datetime | None = None
    last_error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceProbeRequest(BaseModel):
    include_disabled: bool = False
    limit: int | None = Field(default=None, ge=1)
    force: bool = False


class ArxivSourceFetchRequest(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1)


class GithubReleaseFetchRequest(BaseModel):
    repository: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1)


class SourceFetchRequest(BaseModel):
    source_id: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1)
    query: str | None = None
    force: bool = False


class SourceCategoryFetchRequest(BaseModel):
    category: str = Field(min_length=1)
    limit_per_source: int = Field(default=5, ge=1)
    enabled_only: bool = True
    priority: str | None = None
    language: str | None = None
    region: str | None = None
    force: bool = False


class SourcePriorityFetchRequest(BaseModel):
    priority: str = Field(min_length=1)
    limit_per_source: int = Field(default=5, ge=1)
    enabled_only: bool = True
    force: bool = False


class SourceTopicFetchRequest(BaseModel):
    topic: str = Field(min_length=1)
    limit_per_source: int = Field(default=5, ge=1)
    enabled_only: bool = True
    category: str | None = None
    priority: str | None = None
    language: str | None = None
    region: str | None = None
    force: bool = False


class EntityCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    kind: Literal["company", "project", "person", "organization"] = "company"
    aliases: list[str] = Field(default_factory=list)
    entity_id: str | None = None
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class TopicSubscriptionCreateRequest(BaseModel):
    topic: str = Field(min_length=1)
    cadence: Literal["daily", "weekly"] = "weekly"
    profile: str = "research"
    source_limit: int = Field(default=5, ge=1)
    subscription_id: str | None = None
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScheduleUpsertRequest(BaseModel):
    schedule_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    trigger_type: Literal["interval", "manual"] = "interval"
    interval_seconds: int = Field(default=86400, ge=1)
    run_at: datetime | None = None
    task_type: str = Field(min_length=1)
    payload_template: dict[str, Any] = Field(default_factory=dict)
    queue_name: str = Field(default="news:queue:memory", min_length=1)
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScheduleView(BaseModel):
    schedule_id: str
    name: str
    trigger_type: str
    enabled: bool = True
    task_type: str | None = None
    queue_name: str | None = None
    interval_seconds: int | None = None
    run_at: datetime | None = None
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScheduleTickRequest(BaseModel):
    now: datetime | None = None
    include_disabled: bool = False


class ManualScheduleTriggerRequest(BaseModel):
    now: datetime | None = None


class ApprovalSubmitRequest(BaseModel):
    requested_action: str
    risk_level: str = "medium"
    reason: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    task_id: str | None = None
    run_id: str | None = None
    requested_by: str | None = None
    expires_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApprovalView(BaseModel):
    approval_id: str
    requested_action: str
    status: str
    risk_level: str = "medium"
    reason: str | None = None
    task_id: str | None = None
    run_id: str | None = None
    requested_by: str | None = None
    requested_at: datetime | None = None
    expires_at: datetime | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None
    decision_type: str | None = None
    modifications: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApprovalDecisionRequest(BaseModel):
    decided_by: str
    reason: str | None = None


class ApprovalModifyRequest(ApprovalDecisionRequest):
    modifications: dict[str, Any] = Field(default_factory=dict)


class ApprovalResumeContextRequest(BaseModel):
    decision_key: str = Field(default="human_review_decision", min_length=1)
