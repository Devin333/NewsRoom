from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.policy import HarnessBudget
from framework.harness.workflow.spec import HarnessWorkflowSpec
from framework.shared.json import stable_json_dumps, to_jsonable
from framework.shared.time import ensure_utc, format_datetime, utc_now


class HarnessRunStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    PLANNING = "planning"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    REPLANNING = "replanning"
    WAITING_APPROVAL = "waiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    HALTED = "halted"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class HarnessStepStatus(StrEnum):
    PENDING = "pending"
    PLANNING = "planning"
    PLAN_VERIFIED = "plan_verified"
    RUNNING = "running"
    VERIFYING = "verifying"
    RETRYING = "retrying"
    REPLANNING = "replanning"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    WAITING_APPROVAL = "waiting_approval"
    HALTED = "halted"


@dataclass(frozen=True)
class HarnessRunSpec:
    run_id: str
    workflow: HarnessWorkflowSpec
    inputs: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    budget: HarnessBudget = field(default_factory=HarnessBudget.safe_default)
    created_at: Any = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not str(self.run_id).strip():
            raise HarnessValidationError("run_id is required")
        if not isinstance(self.workflow, HarnessWorkflowSpec):
            raise HarnessValidationError("workflow must be HarnessWorkflowSpec")
        if not isinstance(self.budget, HarnessBudget):
            raise HarnessValidationError("budget must be HarnessBudget")
        if (
            not isinstance(self.created_at, datetime)
            or self.created_at.tzinfo is None
            or self.created_at.utcoffset() is None
        ):
            raise HarnessValidationError("created_at must be a timezone-aware datetime")
        try:
            stable_json_dumps(self.inputs)
            stable_json_dumps(self.metadata)
        except TypeError as exc:
            raise HarnessValidationError("inputs and metadata must be serializable") from exc
        object.__setattr__(self, "run_id", str(self.run_id))
        object.__setattr__(self, "inputs", dict(self.inputs))
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "workflow": self.workflow.to_dict(),
            "inputs": to_jsonable(self.inputs),
            "metadata": to_jsonable(self.metadata),
            "budget": self.budget.to_dict(),
            "created_at": format_datetime(self.created_at),
        }


@dataclass(frozen=True)
class HarnessStepState:
    step_id: str
    status: HarnessStepStatus | str = HarnessStepStatus.PENDING
    attempts: int = 0
    replans: int = 0
    output_ref: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: Any = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not str(self.step_id).strip():
            raise HarnessValidationError("step_id is required")
        if self.attempts < 0:
            raise HarnessValidationError("attempts must not be negative")
        if self.replans < 0:
            raise HarnessValidationError("replans must not be negative")
        object.__setattr__(self, "step_id", str(self.step_id))
        object.__setattr__(self, "status", HarnessStepStatus(self.status))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "status": self.status.value,
            "attempts": self.attempts,
            "replans": self.replans,
            "output_ref": self.output_ref,
            "error": self.error,
            "metadata": to_jsonable(self.metadata),
            "updated_at": format_datetime(self.updated_at),
        }


@dataclass(frozen=True)
class HarnessState:
    run_spec: HarnessRunSpec
    status: HarnessRunStatus | str = HarnessRunStatus.CREATED
    step_states: tuple[HarnessStepState, ...] = ()
    current_step_id: str | None = None
    turn_count: int = 0
    replan_count: int = 0
    worker_call_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: Any = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not isinstance(self.run_spec, HarnessRunSpec):
            raise HarnessValidationError("run_spec must be HarnessRunSpec")
        object.__setattr__(self, "status", HarnessRunStatus(self.status))
        if not all(isinstance(step_state, HarnessStepState) for step_state in self.step_states):
            raise HarnessValidationError("step_states must be HarnessStepState values")
        declared_steps = set(self.run_spec.workflow.step_ids)
        state_steps = [step_state.step_id for step_state in self.step_states]
        for step_id in state_steps:
            if step_id not in declared_steps:
                raise HarnessValidationError("step state must reference a workflow step")
        if self.current_step_id is not None and self.current_step_id not in declared_steps:
            raise HarnessValidationError("current_step_id must reference a workflow step")
        if self.turn_count < 0 or self.replan_count < 0 or self.worker_call_count < 0:
            raise HarnessValidationError("state counters must not be negative")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @classmethod
    def initial(cls, run_spec: HarnessRunSpec) -> "HarnessState":
        return cls(
            run_spec=run_spec,
            step_states=tuple(
                HarnessStepState(step_id=step_id, updated_at=run_spec.created_at)
                for step_id in run_spec.workflow.step_ids
            ),
            current_step_id=run_spec.workflow.entry_step_id,
            updated_at=run_spec.created_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_spec": self.run_spec.to_dict(),
            "status": self.status.value,
            "step_states": [step_state.to_dict() for step_state in self.step_states],
            "current_step_id": self.current_step_id,
            "turn_count": self.turn_count,
            "replan_count": self.replan_count,
            "worker_call_count": self.worker_call_count,
            "metadata": to_jsonable(self.metadata),
            "updated_at": format_datetime(self.updated_at),
        }


__all__ = [
    "HarnessRunSpec",
    "HarnessRunStatus",
    "HarnessState",
    "HarnessStepState",
    "HarnessStepStatus",
]
