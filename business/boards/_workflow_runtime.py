from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import Field, model_validator

from business.foundation import PrimitiveModel


class WorkflowStageStatus(str, Enum):
    SUCCESS = "success"
    WARNING = "warning"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowRecoveryAction(str, Enum):
    NONE = "none"
    REVIEW = "review"
    BLOCK = "block"
    RETRY = "retry"
    FALLBACK = "fallback"
    SKIP = "skip"


class BoardWorkflowStageResult(PrimitiveModel):
    stage_name: str
    status: WorkflowStageStatus
    started_at: datetime
    finished_at: datetime
    duration_ms: float
    input_count: int | None = None
    output_count: int | None = None
    warnings: list[str] = Field(default_factory=list)
    error_type: str | None = None
    error_message: str | None = None
    recovery_action: WorkflowRecoveryAction = WorkflowRecoveryAction.NONE
    quality_checks: list[dict[str, Any]] = Field(default_factory=list)
    feedback_events: list[dict[str, Any]] = Field(default_factory=list)
    guard_results: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_duration(self) -> "BoardWorkflowStageResult":
        if self.duration_ms < 0.0:
            object.__setattr__(self, "duration_ms", 0.0)
        return self


class BoardWorkflowExecution(PrimitiveModel):
    workflow_id: str
    board_type: str
    stages: list[BoardWorkflowStageResult] = Field(default_factory=list)
    status: WorkflowStageStatus = WorkflowStageStatus.SUCCESS
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def stage_count(self) -> int:
        return len(self.stages)

    @property
    def failed_stage_count(self) -> int:
        return sum(1 for stage in self.stages if stage.status == WorkflowStageStatus.FAILED)

    @property
    def warning_stage_count(self) -> int:
        return sum(1 for stage in self.stages if stage.status == WorkflowStageStatus.WARNING)

    def add_stage(self, stage: BoardWorkflowStageResult) -> "BoardWorkflowExecution":
        stages = [*self.stages, stage]
        status = _status_from_stages(stages)
        return self.model_copy(update={"stages": stages, "status": status})

    def finish(self) -> "BoardWorkflowExecution":
        return self.model_copy(update={"finished_at": datetime.now(UTC), "status": _status_from_stages(self.stages)})

    def to_metadata(self) -> dict[str, Any]:
        return {
            "workflow_execution": self.to_dict(),
            "stage_count": self.stage_count,
            "failed_stage_count": self.failed_stage_count,
            "warning_stage_count": self.warning_stage_count,
        }


def stage_result(
    stage_name: str,
    *,
    started_at: datetime,
    input_count: int | None = None,
    output_count: int | None = None,
    warnings: list[str] | None = None,
    error: BaseException | None = None,
    quality_checks: list[dict[str, Any]] | None = None,
    feedback_events: list[dict[str, Any]] | None = None,
    guard_results: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> BoardWorkflowStageResult:
    finished_at = datetime.now(UTC)
    duration_ms = max(0.0, (finished_at - started_at).total_seconds() * 1000.0)
    warning_values = [str(warning) for warning in warnings or [] if str(warning).strip()]
    if error is not None:
        return BoardWorkflowStageResult(
            stage_name=stage_name,
            status=WorkflowStageStatus.FAILED,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            input_count=input_count,
            output_count=output_count,
            warnings=warning_values,
            error_type=type(error).__name__,
            error_message=str(error),
            recovery_action=WorkflowRecoveryAction.BLOCK,
            quality_checks=list(quality_checks or []),
            feedback_events=list(feedback_events or []),
            guard_results=list(guard_results or []),
            metadata=metadata or {},
        )
    status = WorkflowStageStatus.WARNING if warning_values else WorkflowStageStatus.SUCCESS
    recovery = WorkflowRecoveryAction.REVIEW if warning_values else WorkflowRecoveryAction.NONE
    return BoardWorkflowStageResult(
        stage_name=stage_name,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        input_count=input_count,
        output_count=output_count,
        warnings=warning_values,
        recovery_action=recovery,
        quality_checks=list(quality_checks or []),
        feedback_events=list(feedback_events or []),
        guard_results=list(guard_results or []),
        metadata=metadata or {},
    )


def skipped_stage_result(
    stage_name: str,
    *,
    reason: str,
    started_at: datetime | None = None,
    metadata: dict[str, Any] | None = None,
) -> BoardWorkflowStageResult:
    now = datetime.now(UTC)
    started = started_at or now
    return BoardWorkflowStageResult(
        stage_name=stage_name,
        status=WorkflowStageStatus.SKIPPED,
        started_at=started,
        finished_at=now,
        duration_ms=max(0.0, (now - started).total_seconds() * 1000.0),
        warnings=[str(reason)],
        recovery_action=WorkflowRecoveryAction.SKIP,
        metadata=metadata or {},
    )


def _status_from_stages(stages: list[BoardWorkflowStageResult]) -> WorkflowStageStatus:
    if any(stage.status == WorkflowStageStatus.FAILED for stage in stages):
        return WorkflowStageStatus.FAILED
    if any(stage.status == WorkflowStageStatus.WARNING for stage in stages):
        return WorkflowStageStatus.WARNING
    if stages and all(stage.status == WorkflowStageStatus.SKIPPED for stage in stages):
        return WorkflowStageStatus.SKIPPED
    return WorkflowStageStatus.SUCCESS


__all__ = [
    "BoardWorkflowExecution",
    "BoardWorkflowStageResult",
    "WorkflowRecoveryAction",
    "WorkflowStageStatus",
    "skipped_stage_result",
    "stage_result",
]
