from __future__ import annotations

from dataclasses import replace
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.state import (
    HarnessRunStatus,
    HarnessState,
    HarnessStepState,
    HarnessStepStatus,
)
from framework.shared.time import utc_now


RUN_TRANSITIONS: dict[HarnessRunStatus, frozenset[HarnessRunStatus]] = {
    HarnessRunStatus.CREATED: frozenset({HarnessRunStatus.RUNNING}),
    HarnessRunStatus.RUNNING: frozenset(
        {
            HarnessRunStatus.PLANNING,
            HarnessRunStatus.EXECUTING,
            HarnessRunStatus.VERIFYING,
            HarnessRunStatus.WAITING_APPROVAL,
            HarnessRunStatus.SUCCEEDED,
            HarnessRunStatus.FAILED,
            HarnessRunStatus.HALTED,
            HarnessRunStatus.BLOCKED,
            HarnessRunStatus.CANCELLED,
        }
    ),
    HarnessRunStatus.PLANNING: frozenset(
        {HarnessRunStatus.EXECUTING, HarnessRunStatus.REPLANNING, HarnessRunStatus.HALTED}
    ),
    HarnessRunStatus.EXECUTING: frozenset(
        {
            HarnessRunStatus.VERIFYING,
            HarnessRunStatus.RUNNING,
            HarnessRunStatus.WAITING_APPROVAL,
            HarnessRunStatus.FAILED,
            HarnessRunStatus.HALTED,
            HarnessRunStatus.BLOCKED,
        }
    ),
    HarnessRunStatus.VERIFYING: frozenset(
        {
            HarnessRunStatus.RUNNING,
            HarnessRunStatus.REPLANNING,
            HarnessRunStatus.FAILED,
            HarnessRunStatus.HALTED,
            HarnessRunStatus.WAITING_APPROVAL,
        }
    ),
    HarnessRunStatus.REPLANNING: frozenset({HarnessRunStatus.PLANNING, HarnessRunStatus.HALTED}),
    HarnessRunStatus.WAITING_APPROVAL: frozenset({HarnessRunStatus.RUNNING, HarnessRunStatus.CANCELLED}),
    HarnessRunStatus.SUCCEEDED: frozenset(),
    HarnessRunStatus.FAILED: frozenset(),
    HarnessRunStatus.HALTED: frozenset(),
    HarnessRunStatus.CANCELLED: frozenset(),
    HarnessRunStatus.BLOCKED: frozenset({HarnessRunStatus.RUNNING, HarnessRunStatus.CANCELLED}),
}


STEP_TRANSITIONS: dict[HarnessStepStatus, frozenset[HarnessStepStatus]] = {
    HarnessStepStatus.PENDING: frozenset(
        {HarnessStepStatus.PLANNING, HarnessStepStatus.SKIPPED, HarnessStepStatus.HALTED}
    ),
    HarnessStepStatus.PLANNING: frozenset(
        {HarnessStepStatus.PLAN_VERIFIED, HarnessStepStatus.REPLANNING, HarnessStepStatus.HALTED}
    ),
    HarnessStepStatus.PLAN_VERIFIED: frozenset({HarnessStepStatus.RUNNING, HarnessStepStatus.HALTED}),
    HarnessStepStatus.RUNNING: frozenset(
        {
            HarnessStepStatus.VERIFYING,
            HarnessStepStatus.RETRYING,
            HarnessStepStatus.FAILED,
            HarnessStepStatus.WAITING_APPROVAL,
            HarnessStepStatus.HALTED,
        }
    ),
    HarnessStepStatus.VERIFYING: frozenset(
        {
            HarnessStepStatus.SUCCEEDED,
            HarnessStepStatus.REPLANNING,
            HarnessStepStatus.FAILED,
            HarnessStepStatus.WAITING_APPROVAL,
            HarnessStepStatus.HALTED,
        }
    ),
    HarnessStepStatus.RETRYING: frozenset({HarnessStepStatus.RUNNING}),
    HarnessStepStatus.REPLANNING: frozenset({HarnessStepStatus.PLANNING, HarnessStepStatus.HALTED}),
    HarnessStepStatus.SUCCEEDED: frozenset(),
    HarnessStepStatus.FAILED: frozenset(),
    HarnessStepStatus.SKIPPED: frozenset(),
    HarnessStepStatus.WAITING_APPROVAL: frozenset({HarnessStepStatus.RUNNING, HarnessStepStatus.HALTED}),
    HarnessStepStatus.HALTED: frozenset(),
}


def transition_run(
    state: HarnessState,
    status: HarnessRunStatus | str,
    *,
    metadata: dict[str, Any] | None = None,
) -> HarnessState:
    next_status = HarnessRunStatus(status)
    if next_status not in RUN_TRANSITIONS[state.status]:
        raise HarnessValidationError(
            "illegal Harness run transition",
            details={"from": state.status.value, "to": next_status.value},
        )
    return replace(
        state,
        status=next_status,
        metadata={**state.metadata, **(metadata or {})},
        updated_at=utc_now(),
    )


def transition_step(
    state: HarnessState,
    step_id: str,
    status: HarnessStepStatus | str,
    *,
    attempts: int | None = None,
    replans: int | None = None,
    output_ref: str | None = None,
    error: str | None = None,
    metadata: dict[str, Any] | None = None,
    current_step_id: str | None = None,
    turn_increment: int = 0,
    replan_increment: int = 0,
    worker_call_increment: int = 0,
) -> HarnessState:
    step_state = get_step_state(state, step_id)
    next_status = HarnessStepStatus(status)
    if next_status not in STEP_TRANSITIONS[step_state.status]:
        raise HarnessValidationError(
            "illegal Harness step transition",
            details={"step_id": step_id, "from": step_state.status.value, "to": next_status.value},
        )
    updated_step = replace(
        step_state,
        status=next_status,
        attempts=step_state.attempts if attempts is None else attempts,
        replans=step_state.replans if replans is None else replans,
        output_ref=step_state.output_ref if output_ref is None else output_ref,
        error=error,
        metadata={**step_state.metadata, **(metadata or {})},
        updated_at=utc_now(),
    )
    return replace_step_state(
        state,
        updated_step,
        current_step_id=step_id if current_step_id is None else current_step_id,
        turn_increment=turn_increment,
        replan_increment=replan_increment,
        worker_call_increment=worker_call_increment,
    )


def replace_step_state(
    state: HarnessState,
    step_state: HarnessStepState,
    *,
    current_step_id: str | None = None,
    turn_increment: int = 0,
    replan_increment: int = 0,
    worker_call_increment: int = 0,
    metadata: dict[str, Any] | None = None,
) -> HarnessState:
    if turn_increment < 0 or replan_increment < 0 or worker_call_increment < 0:
        raise HarnessValidationError("state counter increments must not be negative")
    replaced = tuple(
        step_state if existing.step_id == step_state.step_id else existing for existing in state.step_states
    )
    if not any(existing.step_id == step_state.step_id for existing in state.step_states):
        raise HarnessValidationError("step state must reference a workflow step")
    return replace(
        state,
        step_states=replaced,
        current_step_id=current_step_id,
        turn_count=state.turn_count + turn_increment,
        replan_count=state.replan_count + replan_increment,
        worker_call_count=state.worker_call_count + worker_call_increment,
        metadata={**state.metadata, **(metadata or {})},
        updated_at=utc_now(),
    )


def get_step_state(state: HarnessState, step_id: str) -> HarnessStepState:
    for step_state in state.step_states:
        if step_state.step_id == step_id:
            return step_state
    raise HarnessValidationError("step_id must reference a workflow step", details={"step_id": step_id})


def terminal_step_statuses() -> frozenset[HarnessStepStatus]:
    return frozenset(
        {
            HarnessStepStatus.SUCCEEDED,
            HarnessStepStatus.FAILED,
            HarnessStepStatus.SKIPPED,
            HarnessStepStatus.HALTED,
        }
    )


def terminal_run_statuses() -> frozenset[HarnessRunStatus]:
    return frozenset(
        {
            HarnessRunStatus.SUCCEEDED,
            HarnessRunStatus.FAILED,
            HarnessRunStatus.HALTED,
            HarnessRunStatus.CANCELLED,
        }
    )


__all__ = [
    "RUN_TRANSITIONS",
    "STEP_TRANSITIONS",
    "get_step_state",
    "replace_step_state",
    "terminal_run_statuses",
    "terminal_step_statuses",
    "transition_run",
    "transition_step",
]
