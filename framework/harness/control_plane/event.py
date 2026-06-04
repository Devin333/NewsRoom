from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.shared.json import to_jsonable
from framework.shared.time import format_datetime, utc_now


class HarnessEventType(StrEnum):
    RUN_CREATED = "run_created"
    RUN_STATE_CHANGED = "run_state_changed"
    STEP_STATE_CHANGED = "step_state_changed"
    PHASE_RECORDED = "phase_recorded"
    DECISION_RECORDED = "decision_recorded"
    WORKER_CALLED = "worker_called"
    WORKER_RESULT_RECORDED = "worker_result_recorded"
    GATE_EVALUATED = "gate_evaluated"
    CHECKPOINT_CREATED = "checkpoint_created"


@dataclass(frozen=True)
class HarnessEvent:
    event_type: HarnessEventType | str
    run_id: str
    step_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    occurred_at: Any = field(default_factory=utc_now)
    trace_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_type", HarnessEventType(self.event_type))
        if not str(self.run_id).strip():
            raise HarnessValidationError("run_id is required")
        object.__setattr__(self, "run_id", str(self.run_id))
        object.__setattr__(self, "payload", dict(self.payload))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type.value,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "payload": to_jsonable(self.payload),
            "metadata": to_jsonable(self.metadata),
            "occurred_at": format_datetime(self.occurred_at),
            "trace_id": self.trace_id,
        }


__all__ = ["HarnessEvent", "HarnessEventType"]
