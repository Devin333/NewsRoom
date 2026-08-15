from __future__ import annotations

import pytest

from framework.harness import (
    HarnessRunSpec,
    HarnessRunStatus,
    HarnessState,
    HarnessStepSpec,
    HarnessStepStatus,
    HarnessValidationError,
)
from framework.harness.workflow.spec import HarnessWorkflowSpec
from framework.harness.control_plane.transitions import get_step_state, transition_run, transition_step


def test_run_transition_rejects_illegal_jump() -> None:
    state = _state()

    with pytest.raises(HarnessValidationError):
        transition_run(state, HarnessRunStatus.SUCCEEDED)


def test_step_transition_rejects_illegal_jump() -> None:
    state = transition_run(_state(), HarnessRunStatus.RUNNING)

    with pytest.raises(HarnessValidationError):
        transition_step(state, "collect", HarnessStepStatus.SUCCEEDED)


def test_bounded_plan_execute_verify_transition_sequence() -> None:
    state = transition_run(_state(), HarnessRunStatus.RUNNING)
    state = transition_run(state, HarnessRunStatus.PLANNING)
    state = transition_step(state, "collect", HarnessStepStatus.PLANNING)
    state = transition_step(state, "collect", HarnessStepStatus.PLAN_VERIFIED)
    state = transition_run(state, HarnessRunStatus.EXECUTING)
    state = transition_step(state, "collect", HarnessStepStatus.RUNNING)
    state = transition_step(state, "collect", HarnessStepStatus.VERIFYING)
    state = transition_run(state, HarnessRunStatus.VERIFYING)
    state = transition_step(state, "collect", HarnessStepStatus.SUCCEEDED)
    state = transition_run(state, HarnessRunStatus.RUNNING)
    state = transition_run(state, HarnessRunStatus.SUCCEEDED)

    assert state.status == HarnessRunStatus.SUCCEEDED
    assert get_step_state(state, "collect").status == HarnessStepStatus.SUCCEEDED


def _state():
    workflow = HarnessWorkflowSpec(
        workflow_id="wf",
        steps=(HarnessStepSpec(step_id="collect", worker_type="llm"),),
        entry_step_id="collect",
    )
    return HarnessState.initial(HarnessRunSpec(run_id="run-transitions", workflow=workflow))
