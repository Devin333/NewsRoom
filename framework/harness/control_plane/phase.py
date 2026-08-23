from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.shared.json import to_jsonable
from framework.shared.time import format_datetime, utc_now


class HarnessPhase(StrEnum):
    PLAN = "plan"
    EXECUTE = "execute"
    VERIFY = "verify"
    REPLAN = "replan"
    HALT = "halt"


class HarnessPhaseBoundary(StrEnum):
    ENTRY = "entry"
    EXIT = "exit"


@dataclass(frozen=True)
class HarnessPhaseRecord:
    phase: HarnessPhase | str
    node_id: str
    boundary: HarnessPhaseBoundary | str = HarnessPhaseBoundary.EXIT
    input_refs: tuple[str, ...] = ()
    output_refs: tuple[str, ...] = ()
    gate_results: tuple[dict[str, Any], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    occurred_at: Any = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "phase", HarnessPhase(self.phase))
        object.__setattr__(self, "boundary", HarnessPhaseBoundary(self.boundary))
        if not str(self.node_id).strip():
            raise HarnessValidationError("node_id is required")
        object.__setattr__(self, "node_id", str(self.node_id))
        object.__setattr__(self, "input_refs", tuple(str(ref) for ref in self.input_refs))
        object.__setattr__(self, "output_refs", tuple(str(ref) for ref in self.output_refs))
        object.__setattr__(self, "gate_results", tuple(dict(result) for result in self.gate_results))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def can_complete_step(self) -> bool:
        return self.phase == HarnessPhase.VERIFY and bool(self.gate_results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase.value,
            "boundary": self.boundary.value,
            "node_id": self.node_id,
            "input_refs": list(self.input_refs),
            "output_refs": list(self.output_refs),
            "gate_results": to_jsonable(list(self.gate_results)),
            "metadata": to_jsonable(self.metadata),
            "occurred_at": format_datetime(self.occurred_at),
        }


def assert_step_completion_allowed(phase_record: HarnessPhaseRecord) -> None:
    if not phase_record.can_complete_step:
        raise HarnessValidationError("step completion requires VERIFY phase with gate results")


__all__ = [
    "HarnessPhase",
    "HarnessPhaseBoundary",
    "HarnessPhaseRecord",
    "assert_step_completion_allowed",
]
