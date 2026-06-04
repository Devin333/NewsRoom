from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.harness.control_plane.event import HarnessEvent
from framework.harness.control_plane.errors import HarnessValidationError
from framework.shared.json import to_jsonable


@dataclass(frozen=True)
class HarnessTrace:
    run_id: str
    events: tuple[HarnessEvent, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.run_id).strip():
            raise HarnessValidationError("run_id is required")
        if not all(isinstance(event, HarnessEvent) for event in self.events):
            raise HarnessValidationError("events must be HarnessEvent values")
        object.__setattr__(self, "run_id", str(self.run_id))
        object.__setattr__(self, "events", tuple(self.events))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def append(self, event: HarnessEvent) -> "HarnessTrace":
        if event.run_id != self.run_id:
            raise HarnessValidationError("event run_id must match trace run_id")
        return HarnessTrace(run_id=self.run_id, events=(*self.events, event), metadata=self.metadata)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "events": [event.to_dict() for event in self.events],
            "metadata": to_jsonable(self.metadata),
        }


__all__ = ["HarnessTrace"]
