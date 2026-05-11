from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


SCHEMA_VERSION = "1.0"


class ApiError(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False
    user_action_required: bool = False


class ApiResponse(BaseModel):
    success: bool
    data: dict[str, Any] | None = None
    error: ApiError | None = None
    request_id: str
    schema_version: str = SCHEMA_VERSION


class DailyRunRequest(BaseModel):
    profile: Literal["live", "live-offline"] = "live-offline"
    topic: str = "AI"
    source_limit: int = Field(default=3, ge=1)
    run_id: str | None = None
    queue_name: str = "news:queue:daily"


class RunResponse(BaseModel):
    run_id: str | None = None
    task_id: str | None = None
    status: Literal["accepted", "queued", "running", "succeeded", "failed", "blocked", "cancelled"]
    task_status: str | None = None
    run_status: str | None = None
    report_status: str | None = None
    report_id: str | None = None
    message: str | None = None


class ReportDetail(BaseModel):
    report_id: str
    run_id: str
    status: str
    title: str | None = None
    report_json: dict[str, Any] | None = None
    report_markdown: str | None = None
    quality_score: float | None = None
    manifest_path: str | None = None


class MemorySearchRequest(BaseModel):
    query: str
    collection: str = "report_sections"
    limit: int = Field(default=5, ge=1)
    filters: dict[str, Any] = Field(default_factory=dict)


class DailyScheduleRequest(BaseModel):
    schedule_id: str = "daily-intelligence"
    name: str = "Daily intelligence"
    trigger_type: Literal["interval", "manual"] = "interval"
    interval_seconds: int = Field(default=86400, ge=1)
    run_at: datetime | None = None
    profile: Literal["live", "live-offline"] = "live-offline"
    topic: str = "AI"
    source_limit: int = Field(default=3, ge=1)
    queue_name: str = "news:queue:daily"


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


class ApprovalDecisionRequest(BaseModel):
    decided_by: str
    reason: str | None = None


class ApprovalModifyRequest(ApprovalDecisionRequest):
    modifications: dict[str, Any] = Field(default_factory=dict)
