from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping
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

    def to_dict(
        self,
        *,
        include_deterministic_history: bool = False,
    ) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "events": [
                event.to_dict(
                    include_deterministic_history=include_deterministic_history
                )
                for event in self.events
            ],
            "metadata": to_jsonable(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HarnessTrace":
        if not isinstance(value, Mapping):
            raise HarnessValidationError("Harness trace payload must be an object")
        payload = dict(value)
        raw_events = payload.pop("events", ())
        if not isinstance(raw_events, (list, tuple)):
            raise HarnessValidationError("Harness trace events must be a list")
        metadata = payload.pop("metadata", {})
        if not isinstance(metadata, Mapping):
            raise HarnessValidationError("Harness trace metadata must be an object")
        try:
            run_id = payload.pop("run_id")
        except KeyError as exc:
            raise HarnessValidationError("Harness trace run_id is required") from exc
        if payload:
            raise HarnessValidationError(
                "Harness trace payload contains unsupported fields: "
                + ", ".join(sorted(payload))
            )
        trace = cls(
            run_id=str(run_id),
            events=tuple(HarnessEvent.from_dict(event) for event in raw_events),
            metadata=dict(metadata),
        )
        if any(event.run_id != trace.run_id for event in trace.events):
            raise HarnessValidationError(
                "Harness trace event run_id must match trace run_id"
            )
        return trace


__all__ = ["HarnessTrace"]
