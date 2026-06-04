from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.workflow.step import HarnessStepSpec
from framework.shared.json import to_jsonable


class HarnessRouteKind(StrEnum):
    ALWAYS = "always"
    ON_VERDICT = "on_verdict"
    ON_STATUS = "on_status"


@dataclass(frozen=True)
class HarnessRoutingRule:
    from_step: str
    to_step: str
    kind: HarnessRouteKind | str = HarnessRouteKind.ALWAYS
    condition: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.from_step).strip():
            raise HarnessValidationError("from_step is required")
        if not str(self.to_step).strip():
            raise HarnessValidationError("to_step is required")
        object.__setattr__(self, "from_step", str(self.from_step))
        object.__setattr__(self, "to_step", str(self.to_step))
        object.__setattr__(self, "kind", HarnessRouteKind(self.kind))
        object.__setattr__(self, "condition", dict(self.condition))

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_step": self.from_step,
            "to_step": self.to_step,
            "kind": self.kind.value,
            "condition": to_jsonable(self.condition),
        }


@dataclass(frozen=True)
class HarnessWorkflowSpec:
    workflow_id: str
    steps: tuple[HarnessStepSpec, ...]
    entry_step_id: str
    terminal_policies: dict[str, Any] = field(default_factory=dict)
    routing_rules: tuple[HarnessRoutingRule, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        workflow_id = str(self.workflow_id).strip()
        entry_step_id = str(self.entry_step_id).strip()
        if not workflow_id:
            raise HarnessValidationError("workflow_id is required")
        if not entry_step_id:
            raise HarnessValidationError("entry_step_id is required")
        if not self.steps:
            raise HarnessValidationError("workflow must contain at least one step")
        if not all(isinstance(step, HarnessStepSpec) for step in self.steps):
            raise HarnessValidationError("steps must be HarnessStepSpec values")
        step_ids = [step.step_id for step in self.steps]
        duplicate_ids = sorted({step_id for step_id in step_ids if step_ids.count(step_id) > 1})
        if duplicate_ids:
            raise HarnessValidationError("step_id values must be unique", details={"duplicates": duplicate_ids})
        if entry_step_id not in step_ids:
            raise HarnessValidationError("entry_step_id must reference a declared step")
        for rule in self.routing_rules:
            if rule.from_step not in step_ids or rule.to_step not in step_ids:
                raise HarnessValidationError("routing rules must reference declared steps")
        object.__setattr__(self, "workflow_id", workflow_id)
        object.__setattr__(self, "entry_step_id", entry_step_id)
        object.__setattr__(self, "terminal_policies", dict(self.terminal_policies))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def step_ids(self) -> tuple[str, ...]:
        return tuple(step.step_id for step in self.steps)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "steps": [step.to_dict() for step in self.steps],
            "entry_step_id": self.entry_step_id,
            "terminal_policies": to_jsonable(self.terminal_policies),
            "routing_rules": [rule.to_dict() for rule in self.routing_rules],
            "metadata": to_jsonable(self.metadata),
        }


__all__ = ["HarnessRouteKind", "HarnessRoutingRule", "HarnessWorkflowSpec"]
