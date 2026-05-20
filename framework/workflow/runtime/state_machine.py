from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from framework.specs import StepStatus, WorkflowStatus


class WorkflowRuntimeEventType(StrEnum):
    START = "start"
    SUCCEED = "succeed"
    FAIL = "fail"
    BLOCK = "block"
    PAUSE = "pause"
    RESUME = "resume"
    REQUEST_HUMAN_REVIEW = "request_human_review"
    HUMAN_REVIEW_APPROVED = "human_review_approved"
    HUMAN_REVIEW_REJECTED = "human_review_rejected"
    BUDGET_EXCEEDED = "budget_exceeded"
    CANCEL = "cancel"
    RERUN_FROM_STEP = "rerun_from_step"
    RESUME_WITH_PATCH = "resume_with_patch"
    MARK_BLOCKED_RESOLVED = "mark_blocked_resolved"


@dataclass(frozen=True)
class WorkflowRuntimeEvent:
    event_type: WorkflowRuntimeEventType
    reason: str | None = None
    step_id: str | None = None
    checkpoint_id: str | None = None
    human_review_request_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_type", WorkflowRuntimeEventType(self.event_type))


class StepRuntimeEventType(StrEnum):
    SCHEDULE = "schedule"
    START = "start"
    SUCCEED = "succeed"
    FAIL = "fail"
    SKIP = "skip"
    BLOCK = "block"
    PAUSE = "pause"
    RESUME = "resume"
    CANCEL = "cancel"
    RETRY = "retry"


@dataclass(frozen=True)
class StepRuntimeEvent:
    event_type: StepRuntimeEventType
    reason: str | None = None
    attempt: int = 1
    checkpoint_id: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_type", StepRuntimeEventType(self.event_type))


class WorkflowStateTransitionError(RuntimeError):
    def __init__(
        self,
        *,
        current: str,
        event: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.current = current
        self.event = event
        self.details = details or {}


class StepStateTransitionError(RuntimeError):
    def __init__(
        self,
        *,
        step_id: str | None,
        current: str,
        event: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.step_id = step_id
        self.current = current
        self.event = event
        self.details = details or {}


WORKFLOW_TRANSITIONS: dict[
    WorkflowStatus,
    dict[WorkflowRuntimeEventType, WorkflowStatus],
] = {
    WorkflowStatus.CREATED: {
        WorkflowRuntimeEventType.START: WorkflowStatus.RUNNING,
        WorkflowRuntimeEventType.CANCEL: WorkflowStatus.CANCELLED,
    },
    WorkflowStatus.RUNNING: {
        WorkflowRuntimeEventType.SUCCEED: WorkflowStatus.SUCCEEDED,
        WorkflowRuntimeEventType.FAIL: WorkflowStatus.FAILED,
        WorkflowRuntimeEventType.BLOCK: WorkflowStatus.BLOCKED,
        WorkflowRuntimeEventType.PAUSE: WorkflowStatus.PAUSED,
        WorkflowRuntimeEventType.REQUEST_HUMAN_REVIEW: WorkflowStatus.WAITING_FOR_HUMAN,
        WorkflowRuntimeEventType.BUDGET_EXCEEDED: WorkflowStatus.BUDGET_EXCEEDED,
        WorkflowRuntimeEventType.CANCEL: WorkflowStatus.CANCELLED,
    },
    WorkflowStatus.PAUSED: {
        WorkflowRuntimeEventType.RESUME: WorkflowStatus.RUNNING,
        WorkflowRuntimeEventType.RESUME_WITH_PATCH: WorkflowStatus.RUNNING,
        WorkflowRuntimeEventType.CANCEL: WorkflowStatus.CANCELLED,
    },
    WorkflowStatus.WAITING_FOR_HUMAN: {
        WorkflowRuntimeEventType.HUMAN_REVIEW_APPROVED: WorkflowStatus.RUNNING,
        WorkflowRuntimeEventType.HUMAN_REVIEW_REJECTED: WorkflowStatus.BLOCKED,
        WorkflowRuntimeEventType.CANCEL: WorkflowStatus.CANCELLED,
    },
    WorkflowStatus.BLOCKED: {
        WorkflowRuntimeEventType.MARK_BLOCKED_RESOLVED: WorkflowStatus.RUNNING,
        WorkflowRuntimeEventType.RERUN_FROM_STEP: WorkflowStatus.RUNNING,
        WorkflowRuntimeEventType.CANCEL: WorkflowStatus.CANCELLED,
    },
    WorkflowStatus.FAILED: {
        WorkflowRuntimeEventType.RERUN_FROM_STEP: WorkflowStatus.RUNNING,
    },
    WorkflowStatus.BUDGET_EXCEEDED: {
        WorkflowRuntimeEventType.RESUME_WITH_PATCH: WorkflowStatus.RUNNING,
        WorkflowRuntimeEventType.CANCEL: WorkflowStatus.CANCELLED,
    },
    WorkflowStatus.RETRYING: {
        WorkflowRuntimeEventType.RESUME: WorkflowStatus.RUNNING,
        WorkflowRuntimeEventType.CANCEL: WorkflowStatus.CANCELLED,
    },
    WorkflowStatus.SUCCEEDED: {},
    WorkflowStatus.CANCELLED: {},
}


STEP_TRANSITIONS: dict[
    StepStatus,
    dict[StepRuntimeEventType, StepStatus],
] = {
    StepStatus.PENDING: {
        StepRuntimeEventType.SCHEDULE: StepStatus.READY,
        StepRuntimeEventType.SKIP: StepStatus.SKIPPED,
        StepRuntimeEventType.BLOCK: StepStatus.BLOCKED,
        StepRuntimeEventType.CANCEL: StepStatus.CANCELLED,
    },
    StepStatus.READY: {
        StepRuntimeEventType.START: StepStatus.RUNNING,
        StepRuntimeEventType.SKIP: StepStatus.SKIPPED,
        StepRuntimeEventType.BLOCK: StepStatus.BLOCKED,
        StepRuntimeEventType.CANCEL: StepStatus.CANCELLED,
    },
    StepStatus.RUNNING: {
        StepRuntimeEventType.SUCCEED: StepStatus.SUCCEEDED,
        StepRuntimeEventType.FAIL: StepStatus.FAILED,
        StepRuntimeEventType.SKIP: StepStatus.SKIPPED,
        StepRuntimeEventType.PAUSE: StepStatus.PAUSED,
        StepRuntimeEventType.BLOCK: StepStatus.BLOCKED,
        StepRuntimeEventType.CANCEL: StepStatus.CANCELLED,
    },
    StepStatus.FAILED: {
        StepRuntimeEventType.RETRY: StepStatus.READY,
    },
    StepStatus.PAUSED: {
        StepRuntimeEventType.RESUME: StepStatus.READY,
        StepRuntimeEventType.CANCEL: StepStatus.CANCELLED,
    },
    StepStatus.BLOCKED: {
        StepRuntimeEventType.RESUME: StepStatus.READY,
        StepRuntimeEventType.CANCEL: StepStatus.CANCELLED,
    },
    StepStatus.RETRYING: {
        StepRuntimeEventType.SCHEDULE: StepStatus.READY,
        StepRuntimeEventType.CANCEL: StepStatus.CANCELLED,
    },
    StepStatus.TIMEOUT: {
        StepRuntimeEventType.RETRY: StepStatus.READY,
        StepRuntimeEventType.CANCEL: StepStatus.CANCELLED,
    },
    StepStatus.SUCCEEDED: {
        StepRuntimeEventType.SCHEDULE: StepStatus.READY,
    },
    StepStatus.SKIPPED: {},
    StepStatus.CANCELLED: {},
}


class WorkflowStateMachine:
    terminal_statuses: set[WorkflowStatus] = {
        WorkflowStatus.SUCCEEDED,
        WorkflowStatus.FAILED,
        WorkflowStatus.CANCELLED,
    }

    def transition(
        self,
        current: WorkflowStatus,
        event: WorkflowRuntimeEvent,
    ) -> WorkflowStatus:
        current = WorkflowStatus(current)
        self._validate_event_requirements(current, event)
        allowed = WORKFLOW_TRANSITIONS.get(current, {})
        target = allowed.get(event.event_type)

        if target is None:
            raise WorkflowStateTransitionError(
                current=current.value,
                event=event.event_type.value,
                message=(
                    "Illegal workflow status transition: "
                    f"{current.value} --{event.event_type.value}--> ?"
                ),
                details={
                    "current": current.value,
                    "event": event.event_type.value,
                    "reason": event.reason,
                },
            )

        return target

    def is_terminal(self, status: WorkflowStatus) -> bool:
        return WorkflowStatus(status) in self.terminal_statuses

    def assert_can_schedule(self, status: WorkflowStatus) -> None:
        status = WorkflowStatus(status)
        if self.is_terminal(status):
            raise WorkflowStateTransitionError(
                current=status.value,
                event="schedule_step",
                message=f"Cannot schedule step when workflow is terminal: {status.value}",
            )
        if status == WorkflowStatus.BUDGET_EXCEEDED:
            raise WorkflowStateTransitionError(
                current=status.value,
                event="schedule_step",
                message="Cannot schedule step when workflow budget is exceeded.",
            )
        if status == WorkflowStatus.BLOCKED:
            raise WorkflowStateTransitionError(
                current=status.value,
                event="schedule_step",
                message="Cannot schedule step when workflow is blocked.",
            )
        if status == WorkflowStatus.PAUSED:
            raise WorkflowStateTransitionError(
                current=status.value,
                event="schedule_step",
                message="Cannot schedule step when workflow is paused.",
            )
        if status == WorkflowStatus.WAITING_FOR_HUMAN:
            raise WorkflowStateTransitionError(
                current=status.value,
                event="schedule_step",
                message="Cannot schedule step while waiting for human review.",
            )

    def _validate_event_requirements(
        self,
        current: WorkflowStatus,
        event: WorkflowRuntimeEvent,
    ) -> None:
        if event.event_type == WorkflowRuntimeEventType.PAUSE and not event.checkpoint_id:
            raise WorkflowStateTransitionError(
                current=current.value,
                event=event.event_type.value,
                message="PAUSE transition requires checkpoint_id.",
                details={"reason": event.reason},
            )
        if (
            event.event_type == WorkflowRuntimeEventType.REQUEST_HUMAN_REVIEW
            and not event.human_review_request_id
        ):
            raise WorkflowStateTransitionError(
                current=current.value,
                event=event.event_type.value,
                message="REQUEST_HUMAN_REVIEW transition requires human_review_request_id.",
                details={"reason": event.reason},
            )
        if event.event_type == WorkflowRuntimeEventType.RERUN_FROM_STEP and not event.step_id:
            raise WorkflowStateTransitionError(
                current=current.value,
                event=event.event_type.value,
                message="RERUN_FROM_STEP requires step_id.",
            )
        if (
            event.event_type == WorkflowRuntimeEventType.RESUME_WITH_PATCH
            and "patch_id" not in event.metadata
        ):
            raise WorkflowStateTransitionError(
                current=current.value,
                event=event.event_type.value,
                message="RESUME_WITH_PATCH requires metadata.patch_id.",
            )
        if (
            event.event_type == WorkflowRuntimeEventType.MARK_BLOCKED_RESOLVED
            and not event.reason
        ):
            raise WorkflowStateTransitionError(
                current=current.value,
                event=event.event_type.value,
                message="MARK_BLOCKED_RESOLVED requires reason.",
            )


class StepStateMachine:
    terminal_statuses: set[StepStatus] = {
        StepStatus.SUCCEEDED,
        StepStatus.FAILED,
        StepStatus.SKIPPED,
        StepStatus.CANCELLED,
    }

    def transition(
        self,
        current: StepStatus,
        event: StepRuntimeEvent,
        *,
        step_id: str | None = None,
    ) -> StepStatus:
        current = StepStatus(current)
        self._validate_event_requirements(current, event, step_id=step_id)
        allowed = STEP_TRANSITIONS.get(current, {})
        target = allowed.get(event.event_type)

        if target is None:
            raise StepStateTransitionError(
                step_id=step_id,
                current=current.value,
                event=event.event_type.value,
                message=(
                    "Illegal step status transition: "
                    f"{current.value} --{event.event_type.value}--> ?"
                ),
                details={
                    "attempt": event.attempt,
                    "reason": event.reason,
                },
            )

        return target

    def is_terminal(self, status: StepStatus) -> bool:
        return StepStatus(status) in self.terminal_statuses

    def _validate_event_requirements(
        self,
        current: StepStatus,
        event: StepRuntimeEvent,
        *,
        step_id: str | None,
    ) -> None:
        if event.event_type == StepRuntimeEventType.PAUSE and not event.checkpoint_id:
            raise StepStateTransitionError(
                step_id=step_id,
                current=current.value,
                event=event.event_type.value,
                message="Step PAUSE transition requires checkpoint_id.",
            )



