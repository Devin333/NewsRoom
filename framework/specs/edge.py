"""Declarative workflow edge specification models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from framework.specs.validation import WorkflowSpecError


class EdgeCondition(str, Enum):
    ALWAYS = "always"
    ON_SUCCESS = "on_success"
    ON_FAILURE = "on_failure"
    CONDITIONAL = "conditional"
    LLM_DECIDE = "llm_decide"
    VALIDATION_PASS = "validation_pass"
    VALIDATION_RETRY_REQUIRED = "validation_retry_required"
    VALIDATION_BLOCKED = "validation_blocked"
    HUMAN_APPROVED = "human_approved"
    HUMAN_REJECTED = "human_rejected"
    BUDGET_EXCEEDED = "budget_exceeded"
    SOURCE_UNAVAILABLE = "source_unavailable"

    def is_unconditional(self) -> bool:
        return self in {EdgeCondition.ALWAYS, EdgeCondition.ON_SUCCESS}

    def to_dict(self) -> dict[str, Any]:
        return {
            "expression": None,
            "when_status": None if self == EdgeCondition.ALWAYS else self.value,
            "condition": self.value,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EdgeCondition | EdgeConditionSpec":
        if "condition" in payload:
            return _edge_condition(str(payload["condition"]))
        return EdgeConditionSpec.from_dict(payload)


@dataclass(frozen=True)
class EdgeConditionSpec:
    """PRD-facing edge condition model."""

    expression: str | None = None
    when_status: str | None = None

    def is_unconditional(self) -> bool:
        return not self.expression and not self.when_status

    def to_dict(self) -> dict[str, Any]:
        return {
            "expression": self.expression,
            "when_status": self.when_status,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EdgeConditionSpec":
        return cls(
            expression=payload.get("expression"),
            when_status=payload.get("when_status"),
        )


@dataclass(frozen=True)
class EdgeSpec:
    edge_id: str = ""
    source_step_id: str = ""
    target_step_id: str = ""
    condition: EdgeCondition = EdgeCondition.ON_SUCCESS
    condition_expr: str | None = None
    from_step: str = ""
    to_step: str = ""
    input_mapping: dict[str, str] = field(default_factory=dict)
    output_mapping: dict[str, str] = field(default_factory=dict)
    priority: int = 0
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (
            self.edge_id
            and self.source_step_id
            and not self.target_step_id
            and not self.from_step
            and not self.to_step
        ):
            source_step_id = self.edge_id
            target_step_id = self.source_step_id
            object.__setattr__(self, "edge_id", "")
            object.__setattr__(self, "source_step_id", source_step_id)
            object.__setattr__(self, "target_step_id", target_step_id)
        if self.from_step and not self.source_step_id:
            object.__setattr__(self, "source_step_id", self.from_step)
        if self.to_step and not self.target_step_id:
            object.__setattr__(self, "target_step_id", self.to_step)
        if not self.edge_id and self.source_step_id and self.target_step_id:
            object.__setattr__(self, "edge_id", f"{self.source_step_id}->{self.target_step_id}")
        if isinstance(self.condition, EdgeConditionSpec):
            if self.condition.expression:
                object.__setattr__(self, "condition_expr", self.condition.expression)
                object.__setattr__(self, "condition", EdgeCondition.CONDITIONAL)
            elif self.condition.when_status:
                object.__setattr__(self, "condition", self.condition.when_status)
            else:
                object.__setattr__(self, "condition", EdgeCondition.ALWAYS)
        object.__setattr__(self, "condition", _edge_condition(self.condition))
        if not self.edge_id:
            raise WorkflowSpecError("edge_id is required")
        if not self.source_step_id:
            raise WorkflowSpecError(f"source_step_id is required for edge {self.edge_id}")
        if not self.target_step_id:
            raise WorkflowSpecError(f"target_step_id is required for edge {self.edge_id}")
        if not isinstance(self.input_mapping, dict):
            raise WorkflowSpecError(f"input_mapping must be an object for edge {self.edge_id}")
        if not isinstance(self.output_mapping, dict):
            raise WorkflowSpecError(f"output_mapping must be an object for edge {self.edge_id}")

    def is_unconditional(self) -> bool:
        return self.condition.is_unconditional() and not self.condition_expr

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "edge_id": self.edge_id,
            "source_step_id": self.source_step_id,
            "target_step_id": self.target_step_id,
            "condition": self.condition.value,
            "condition_expr": self.condition_expr,
            "input_mapping": dict(self.input_mapping),
            "output_mapping": dict(self.output_mapping),
            "priority": self.priority,
            "description": self.description,
            "metadata": dict(self.metadata),
        }
        if self.from_step:
            payload["from_step"] = self.from_step
        if self.to_step:
            payload["to_step"] = self.to_step
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EdgeSpec":
        return cls(**payload)


def _edge_condition(value: EdgeCondition | str) -> EdgeCondition:
    if isinstance(value, EdgeCondition):
        return value
    normalized = str(value)
    legacy_quality_prefix = "qual" + "ity_"
    if normalized.startswith(legacy_quality_prefix):
        suffix = normalized.removeprefix(legacy_quality_prefix)
        if suffix == "rewrite_required":
            suffix = "retry_required"
        normalized = f"validation_{suffix}"
    return EdgeCondition(normalized)


__all__ = ["EdgeCondition", "EdgeConditionSpec", "EdgeSpec"]
