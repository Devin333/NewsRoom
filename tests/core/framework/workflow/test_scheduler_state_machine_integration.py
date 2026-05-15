from __future__ import annotations

import pytest

from core.framework.specs import EdgeSpec, StepSpec, StepStatus, WorkflowSpec, WorkflowStatus
from core.framework.workflow import RoutingEngine, WorkflowCompiler
from core.framework.workflow.scheduler import (
    StepOutcome,
    StepOutcomeStatus,
    WorkflowScheduler,
    scheduler_state_from_dict,
    scheduler_state_to_dict,
)
from core.framework.workflow.state_machine import WorkflowStateTransitionError


@pytest.mark.parametrize(
    "workflow_status",
    [
        WorkflowStatus.CANCELLED,
        WorkflowStatus.PAUSED,
        WorkflowStatus.WAITING_FOR_HUMAN,
        WorkflowStatus.SUCCEEDED,
        WorkflowStatus.FAILED,
        WorkflowStatus.BLOCKED,
        WorkflowStatus.BUDGET_EXCEEDED,
    ],
)
def test_scheduler_rejects_ready_steps_when_workflow_cannot_schedule(
    workflow_status: WorkflowStatus,
) -> None:
    scheduler = _make_scheduler()
    scheduler.initialize({})

    with pytest.raises(WorkflowStateTransitionError):
        scheduler.next_ready_steps(max_count=1, workflow_status=workflow_status)


def test_scheduler_tracks_step_statuses_through_ready_running_and_success() -> None:
    scheduler = _make_scheduler()
    scheduler.initialize({})

    assert scheduler.state.step_statuses["A"] == StepStatus.READY

    ready = scheduler.next_ready_steps(max_count=1, workflow_status=WorkflowStatus.RUNNING)
    assert [step.step_id for step in ready] == ["A"]
    assert scheduler.state.step_statuses["A"] == StepStatus.RUNNING

    scheduler.mark_step_finished("A", StepOutcome("A", StepOutcomeStatus.SUCCESS))
    assert scheduler.state.step_statuses["A"] == StepStatus.SUCCEEDED
    assert scheduler.state.step_statuses["B"] == StepStatus.READY


def test_scheduler_checkpoint_round_trips_step_statuses() -> None:
    scheduler = _make_scheduler()
    scheduler.initialize({})
    scheduler.next_ready_steps(max_count=1)
    scheduler.mark_step_finished("A", StepOutcome("A", StepOutcomeStatus.SUCCESS))

    checkpoint = scheduler_state_to_dict(scheduler.state)
    restored = scheduler_state_from_dict(checkpoint)

    assert restored.step_statuses["A"] == StepStatus.SUCCEEDED
    assert restored.step_statuses["B"] == StepStatus.READY


def _make_scheduler() -> WorkflowScheduler:
    spec = WorkflowSpec(
        workflow_id="scheduler-state-machine",
        name="Scheduler State Machine",
        version="1.0",
        start_step_id="A",
        terminal_step_ids=["B"],
        steps=[
            StepSpec("A", "test.A", write_keys=["a"]),
            StepSpec("B", "test.B", read_keys=["a"], write_keys=["b"]),
        ],
        edges=[EdgeSpec("A-B", "A", "B")],
    )
    result = WorkflowCompiler().compile(spec)
    assert result.passed
    assert result.graph is not None
    return WorkflowScheduler(
        workflow=spec,
        graph=result.graph,
        routing_engine=RoutingEngine(),
    )
