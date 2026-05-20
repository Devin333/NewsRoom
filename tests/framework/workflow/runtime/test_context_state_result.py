from __future__ import annotations

import pytest

from framework.shared import RuntimeStatus
from framework.workflow.runtime import (
    StepOutcome,
    StepRunContext,
    StepRuntimeState,
    WorkflowResult,
    WorkflowRunContext,
    WorkflowRuntimeState,
)


def test_workflow_run_context_round_trip_and_child_context() -> None:
    context = WorkflowRunContext(
        run_id="run-1",
        workflow_id="wf-1",
        profile="test",
        metadata={"topic": "agents"},
    )

    payload = context.to_dict()
    restored = WorkflowRunContext.from_dict(payload)
    child = restored.child_context(step_id="collect")

    assert restored.run_id == "run-1"
    assert payload["started_at"].endswith("Z")
    assert isinstance(child, StepRunContext)
    assert child.step_id == "collect"
    assert child.attempt == 1


def test_runtime_state_transitions() -> None:
    state = WorkflowRuntimeState(run_id="run-1", workflow_id="wf-1").mark_running()
    state = state.mark_step_started("collect")
    state = state.mark_step_completed("collect")

    assert state.status == RuntimeStatus.RUNNING
    assert state.current_step_ids == []
    assert state.completed_step_ids == ["collect"]
    assert state.step_states["collect"].status == RuntimeStatus.SUCCEEDED

    failed = state.mark_step_failed("draft", "boom")
    assert failed.is_terminal()
    assert failed.failed_step_ids == ["draft"]
    assert WorkflowRuntimeState.from_dict(failed.to_dict()).step_states["draft"].error == "boom"


def test_step_runtime_state_validates_attempt() -> None:
    assert StepRuntimeState(step_id="s1").start().attempt == 1


def test_step_outcome_prd_factories() -> None:
    success = StepOutcome.success("s1", {"ok": True})
    failure = StepOutcome.failure("s2", RuntimeError("boom"))

    assert success.output == {"ok": True}
    assert failure.error is not None
    assert failure.error.details["step_id"] == "s2"


def test_workflow_result_success_and_terminal_output() -> None:
    result = WorkflowResult(
        run_id="run-1",
        workflow_id="wf-1",
        workflow_version="1.0",
        status="succeeded",
        output={"done": True},
    )

    assert result.success
    assert result.runtime_status == RuntimeStatus.SUCCEEDED
    assert result.terminal_output() == {"done": True}
    assert result.to_dict()["started_at"].endswith("Z")


def test_runtime_context_rejects_empty_ids() -> None:
    with pytest.raises(ValueError):
        WorkflowRunContext(run_id="", workflow_id="wf-1", profile="test")


