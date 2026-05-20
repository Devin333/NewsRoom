from __future__ import annotations

from framework.specs import StepStatus, WorkflowStatus
from framework.workflow.runtime.state_machine import StepStateMachine, WorkflowStateMachine
from framework.workflow.runtime.status_classifier import RuntimeStatusClassifier


def test_workflow_status_terminal_semantics_are_centralized() -> None:
    machine = WorkflowStateMachine()

    for status in WorkflowStatus:
        assert status.is_terminal() == RuntimeStatusClassifier.is_terminal_workflow(status)
        assert machine.is_terminal(status) == RuntimeStatusClassifier.is_terminal_workflow(status)

    assert WorkflowStatus.BUDGET_EXCEEDED.is_terminal()
    assert RuntimeStatusClassifier.is_recoverable_workflow(WorkflowStatus.BLOCKED)
    assert RuntimeStatusClassifier.is_waiting_workflow(WorkflowStatus.WAITING_FOR_HUMAN)
    assert RuntimeStatusClassifier.is_active_workflow(WorkflowStatus.RUNNING)


def test_step_status_terminal_semantics_are_centralized() -> None:
    machine = StepStateMachine()

    for status in StepStatus:
        assert status.is_terminal() == RuntimeStatusClassifier.is_terminal_step(status)
        assert machine.is_terminal(status) == RuntimeStatusClassifier.is_terminal_step(status)

    assert StepStatus.TIMEOUT.is_terminal()
    assert RuntimeStatusClassifier.is_retryable_step(StepStatus.TIMEOUT)
    assert RuntimeStatusClassifier.is_waiting_step(StepStatus.PAUSED)
    assert RuntimeStatusClassifier.is_active_step(StepStatus.READY)
