from __future__ import annotations

import pytest

from core.framework.specs import WorkflowStatus
from core.framework.workflow.state_machine import (
    WorkflowRuntimeEvent,
    WorkflowRuntimeEventType,
    WorkflowStateMachine,
    WorkflowStateTransitionError,
)


def test_workflow_created_can_start() -> None:
    assert _transition(WorkflowStatus.CREATED, WorkflowRuntimeEventType.START) == WorkflowStatus.RUNNING


def test_running_can_reach_terminal_and_blocked_statuses() -> None:
    assert _transition(WorkflowStatus.RUNNING, WorkflowRuntimeEventType.SUCCEED) == WorkflowStatus.SUCCEEDED
    assert _transition(WorkflowStatus.RUNNING, WorkflowRuntimeEventType.FAIL) == WorkflowStatus.FAILED
    assert _transition(WorkflowStatus.RUNNING, WorkflowRuntimeEventType.BLOCK) == WorkflowStatus.BLOCKED
    assert _transition(WorkflowStatus.RUNNING, WorkflowRuntimeEventType.CANCEL) == WorkflowStatus.CANCELLED
    assert (
        _transition(WorkflowStatus.RUNNING, WorkflowRuntimeEventType.BUDGET_EXCEEDED)
        == WorkflowStatus.BUDGET_EXCEEDED
    )


def test_pause_requires_checkpoint() -> None:
    sm = WorkflowStateMachine()

    with pytest.raises(WorkflowStateTransitionError, match="checkpoint_id"):
        sm.transition(
            WorkflowStatus.RUNNING,
            WorkflowRuntimeEvent(event_type=WorkflowRuntimeEventType.PAUSE),
        )


def test_running_can_pause_with_checkpoint() -> None:
    sm = WorkflowStateMachine()

    status = sm.transition(
        WorkflowStatus.RUNNING,
        WorkflowRuntimeEvent(
            event_type=WorkflowRuntimeEventType.PAUSE,
            checkpoint_id="checkpoint-1",
        ),
    )

    assert status == WorkflowStatus.PAUSED


def test_waiting_for_human_requires_review_request() -> None:
    sm = WorkflowStateMachine()

    with pytest.raises(WorkflowStateTransitionError, match="human_review_request_id"):
        sm.transition(
            WorkflowStatus.RUNNING,
            WorkflowRuntimeEvent(event_type=WorkflowRuntimeEventType.REQUEST_HUMAN_REVIEW),
        )


def test_running_can_wait_for_human_with_review_request() -> None:
    sm = WorkflowStateMachine()

    status = sm.transition(
        WorkflowStatus.RUNNING,
        WorkflowRuntimeEvent(
            event_type=WorkflowRuntimeEventType.REQUEST_HUMAN_REVIEW,
            human_review_request_id="review-1",
            step_id="review",
        ),
    )

    assert status == WorkflowStatus.WAITING_FOR_HUMAN


def test_paused_and_human_review_can_resume() -> None:
    assert _transition(WorkflowStatus.PAUSED, WorkflowRuntimeEventType.RESUME) == WorkflowStatus.RUNNING
    assert (
        _transition(
            WorkflowStatus.WAITING_FOR_HUMAN,
            WorkflowRuntimeEventType.HUMAN_REVIEW_APPROVED,
        )
        == WorkflowStatus.RUNNING
    )
    assert (
        _transition(
            WorkflowStatus.WAITING_FOR_HUMAN,
            WorkflowRuntimeEventType.HUMAN_REVIEW_REJECTED,
        )
        == WorkflowStatus.BLOCKED
    )


def test_terminal_statuses_cannot_restart_directly() -> None:
    sm = WorkflowStateMachine()

    for status in (
        WorkflowStatus.SUCCEEDED,
        WorkflowStatus.FAILED,
        WorkflowStatus.CANCELLED,
    ):
        with pytest.raises(WorkflowStateTransitionError):
            sm.transition(
                status,
                WorkflowRuntimeEvent(event_type=WorkflowRuntimeEventType.START),
            )


def test_invalid_terminal_transitions_are_rejected() -> None:
    sm = WorkflowStateMachine()

    with pytest.raises(WorkflowStateTransitionError):
        sm.transition(
            WorkflowStatus.FAILED,
            WorkflowRuntimeEvent(event_type=WorkflowRuntimeEventType.SUCCEED),
        )
    with pytest.raises(WorkflowStateTransitionError):
        sm.transition(
            WorkflowStatus.BLOCKED,
            WorkflowRuntimeEvent(event_type=WorkflowRuntimeEventType.SUCCEED),
        )


def test_failed_can_rerun_only_with_step_id() -> None:
    sm = WorkflowStateMachine()

    with pytest.raises(WorkflowStateTransitionError, match="step_id"):
        sm.transition(
            WorkflowStatus.FAILED,
            WorkflowRuntimeEvent(event_type=WorkflowRuntimeEventType.RERUN_FROM_STEP),
        )

    status = sm.transition(
        WorkflowStatus.FAILED,
        WorkflowRuntimeEvent(
            event_type=WorkflowRuntimeEventType.RERUN_FROM_STEP,
            step_id="A",
        ),
    )
    assert status == WorkflowStatus.RUNNING


def test_blocked_can_resume_only_through_explicit_recovery_event() -> None:
    sm = WorkflowStateMachine()

    with pytest.raises(WorkflowStateTransitionError):
        sm.transition(
            WorkflowStatus.BLOCKED,
            WorkflowRuntimeEvent(event_type=WorkflowRuntimeEventType.RESUME),
        )
    with pytest.raises(WorkflowStateTransitionError, match="requires reason"):
        sm.transition(
            WorkflowStatus.BLOCKED,
            WorkflowRuntimeEvent(event_type=WorkflowRuntimeEventType.MARK_BLOCKED_RESOLVED),
        )

    status = sm.transition(
        WorkflowStatus.BLOCKED,
        WorkflowRuntimeEvent(
            event_type=WorkflowRuntimeEventType.MARK_BLOCKED_RESOLVED,
            reason="operator fixed configuration",
        ),
    )
    assert status == WorkflowStatus.RUNNING


def test_resume_with_patch_requires_patch_id() -> None:
    sm = WorkflowStateMachine()

    with pytest.raises(WorkflowStateTransitionError, match="patch_id"):
        sm.transition(
            WorkflowStatus.PAUSED,
            WorkflowRuntimeEvent(event_type=WorkflowRuntimeEventType.RESUME_WITH_PATCH),
        )

    status = sm.transition(
        WorkflowStatus.PAUSED,
        WorkflowRuntimeEvent(
            event_type=WorkflowRuntimeEventType.RESUME_WITH_PATCH,
            metadata={"patch_id": "patch-1"},
        ),
    )
    assert status == WorkflowStatus.RUNNING


def test_assert_can_schedule_rejects_terminal_and_paused_states() -> None:
    sm = WorkflowStateMachine()

    for status in (
        WorkflowStatus.SUCCEEDED,
        WorkflowStatus.FAILED,
        WorkflowStatus.CANCELLED,
        WorkflowStatus.PAUSED,
        WorkflowStatus.WAITING_FOR_HUMAN,
        WorkflowStatus.BLOCKED,
        WorkflowStatus.BUDGET_EXCEEDED,
    ):
        with pytest.raises(WorkflowStateTransitionError):
            sm.assert_can_schedule(status)

    sm.assert_can_schedule(WorkflowStatus.RUNNING)


def _transition(
    current: WorkflowStatus,
    event_type: WorkflowRuntimeEventType,
) -> WorkflowStatus:
    return WorkflowStateMachine().transition(
        current,
        WorkflowRuntimeEvent(event_type=event_type),
    )
