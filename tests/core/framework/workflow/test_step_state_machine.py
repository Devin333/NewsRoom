from __future__ import annotations

import pytest

from core.framework.specs import StepStatus
from core.framework.workflow.state_machine import (
    StepRuntimeEvent,
    StepRuntimeEventType,
    StepStateMachine,
    StepStateTransitionError,
)


def test_step_can_move_from_pending_to_running_and_success() -> None:
    sm = StepStateMachine()

    status = sm.transition(
        StepStatus.PENDING,
        StepRuntimeEvent(event_type=StepRuntimeEventType.SCHEDULE),
        step_id="A",
    )
    assert status == StepStatus.READY

    status = sm.transition(
        status,
        StepRuntimeEvent(event_type=StepRuntimeEventType.START),
        step_id="A",
    )
    assert status == StepStatus.RUNNING

    status = sm.transition(
        status,
        StepRuntimeEvent(event_type=StepRuntimeEventType.SUCCEED),
        step_id="A",
    )
    assert status == StepStatus.SUCCEEDED
    assert sm.is_terminal(status)


def test_running_step_can_fail_and_retry_to_ready() -> None:
    sm = StepStateMachine()

    failed = sm.transition(
        StepStatus.RUNNING,
        StepRuntimeEvent(event_type=StepRuntimeEventType.FAIL, error="boom"),
        step_id="A",
    )
    assert failed == StepStatus.FAILED

    ready = sm.transition(
        failed,
        StepRuntimeEvent(event_type=StepRuntimeEventType.RETRY, attempt=2),
        step_id="A",
    )
    assert ready == StepStatus.READY


def test_step_pause_requires_checkpoint() -> None:
    sm = StepStateMachine()

    with pytest.raises(StepStateTransitionError, match="checkpoint_id"):
        sm.transition(
            StepStatus.RUNNING,
            StepRuntimeEvent(event_type=StepRuntimeEventType.PAUSE),
            step_id="A",
        )


def test_running_step_can_pause_with_checkpoint_then_resume_to_ready() -> None:
    sm = StepStateMachine()

    paused = sm.transition(
        StepStatus.RUNNING,
        StepRuntimeEvent(
            event_type=StepRuntimeEventType.PAUSE,
            checkpoint_id="checkpoint-1",
        ),
        step_id="A",
    )
    assert paused == StepStatus.PAUSED

    ready = sm.transition(
        paused,
        StepRuntimeEvent(event_type=StepRuntimeEventType.RESUME),
        step_id="A",
    )
    assert ready == StepStatus.READY


def test_running_step_can_block_skip_or_cancel() -> None:
    sm = StepStateMachine()

    assert (
        sm.transition(
            StepStatus.RUNNING,
            StepRuntimeEvent(event_type=StepRuntimeEventType.BLOCK),
            step_id="A",
        )
        == StepStatus.BLOCKED
    )
    assert (
        sm.transition(
            StepStatus.READY,
            StepRuntimeEvent(event_type=StepRuntimeEventType.SKIP),
            step_id="B",
        )
        == StepStatus.SKIPPED
    )
    assert (
        sm.transition(
            StepStatus.RUNNING,
            StepRuntimeEvent(event_type=StepRuntimeEventType.CANCEL),
            step_id="C",
        )
        == StepStatus.CANCELLED
    )


def test_terminal_steps_cannot_restart() -> None:
    sm = StepStateMachine()

    for status in (
        StepStatus.SUCCEEDED,
        StepStatus.SKIPPED,
        StepStatus.CANCELLED,
    ):
        with pytest.raises(StepStateTransitionError):
            sm.transition(
                status,
                StepRuntimeEvent(event_type=StepRuntimeEventType.START),
                step_id="A",
            )


def test_succeeded_step_cannot_fail_or_retry() -> None:
    sm = StepStateMachine()

    with pytest.raises(StepStateTransitionError):
        sm.transition(
            StepStatus.SUCCEEDED,
            StepRuntimeEvent(event_type=StepRuntimeEventType.FAIL),
            step_id="A",
        )
    with pytest.raises(StepStateTransitionError):
        sm.transition(
            StepStatus.SUCCEEDED,
            StepRuntimeEvent(event_type=StepRuntimeEventType.RETRY),
            step_id="A",
        )
