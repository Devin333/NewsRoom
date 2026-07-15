from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.shared.json import to_jsonable
from framework.shared.time import format_datetime, utc_now


class HarnessDecisionType(StrEnum):
    START_STEP = "start_step"
    PLAN_STEP = "plan_step"
    EXECUTE_STEP = "execute_step"
    VERIFY_STEP = "verify_step"
    COMPLETE_STEP = "complete_step"
    RETRY_STEP = "retry_step"
    REPLAN_STEP = "replan_step"
    ROUTE_TO_STEP = "route_to_step"
    ROUTE_TO_REPAIR = "route_to_repair"
    WAIT_FOR_APPROVAL = "wait_for_approval"
    RESUME_AFTER_APPROVAL = "resume_after_approval"
    FAIL_RUN = "fail_run"
    COMPLETE_RUN = "complete_run"
    CANCEL_RUN = "cancel_run"
    BLOCK_RUN = "block_run"
    HALT_RUN = "halt_run"


@dataclass(frozen=True)
class HarnessDecision:
    decision_type: HarnessDecisionType | str
    run_id: str
    step_id: str | None = None
    target_step_id: str | None = None
    reason: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    decided_by: str = "harness"
    decided_at: Any = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "decision_type", HarnessDecisionType(self.decision_type))
        if not str(self.run_id).strip():
            raise HarnessValidationError("run_id is required")
        if str(self.decided_by).strip() != "harness":
            raise HarnessValidationError("HarnessDecision must be decided_by='harness'")
        if self.decision_type in {HarnessDecisionType.ROUTE_TO_STEP, HarnessDecisionType.ROUTE_TO_REPAIR} and not self.target_step_id:
            raise HarnessValidationError("route_to_step requires target_step_id")
        object.__setattr__(self, "run_id", str(self.run_id))
        object.__setattr__(self, "payload", dict(self.payload))

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_type": self.decision_type.value,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "target_step_id": self.target_step_id,
            "reason": self.reason,
            "payload": to_jsonable(self.payload),
            "decided_by": self.decided_by,
            "decided_at": format_datetime(self.decided_at),
        }


__all__ = ["HarnessDecision", "HarnessDecisionType"]
