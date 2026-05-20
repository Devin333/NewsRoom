"""Declarative workflow trigger specification models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from framework.specs.validation import WorkflowSpecError


class WorkflowTriggerType(str, Enum):
    MANUAL = "manual"
    SCHEDULE = "schedule"
    SCHEDULED = "scheduled"
    EVENT = "event"
    WEBHOOK = "webhook"


@dataclass(frozen=True)
class WorkflowTriggerSpec:
    trigger_type: str = "manual"
    schedule: str | None = None
    event_type: str | None = None
    trigger_id: str = ""
    config: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.trigger_type, WorkflowTriggerType):
            object.__setattr__(self, "trigger_type", self.trigger_type.value)
        if not self.trigger_type:
            raise WorkflowSpecError("trigger_type is required")
        if not isinstance(self.config, dict):
            raise WorkflowSpecError("config must be an object")

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "trigger_type": self.trigger_type,
            "schedule": self.schedule,
            "event_type": self.event_type,
            "metadata": dict(self.metadata),
        }
        if self.trigger_id:
            payload["trigger_id"] = self.trigger_id
        if self.config:
            payload["config"] = dict(self.config)
        if not self.enabled:
            payload["enabled"] = self.enabled
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WorkflowTriggerSpec":
        return cls(**payload)


__all__ = ["WorkflowTriggerSpec", "WorkflowTriggerType"]
