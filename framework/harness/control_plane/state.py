from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from collections.abc import Mapping
from typing import Any

from framework.events.canonical import checksum_for
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.policy import HarnessBudget
from framework.harness.graph.definition import HarnessGraphDefinition
from framework.shared.json import stable_json_dumps, to_jsonable
from framework.shared.time import ensure_utc, format_datetime, parse_datetime, utc_now


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
    graph: HarnessGraphDefinition
    inputs: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    budget: HarnessBudget = field(default_factory=HarnessBudget.safe_default)
    created_at: Any = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not str(self.run_id).strip():
            raise HarnessValidationError("run_id is required")
        if not isinstance(self.graph, HarnessGraphDefinition):
            raise HarnessValidationError("graph must be HarnessGraphDefinition")
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
            "graph": self.graph.to_dict(),
            "inputs": to_jsonable(self.inputs),
            "metadata": to_jsonable(self.metadata),
            "budget": self.budget.to_dict(),
            "created_at": format_datetime(self.created_at),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HarnessRunSpec":
        """Restore the exact immutable run specification from durable JSON."""

        if not isinstance(value, Mapping):
            raise HarnessValidationError("run specification must be an object")
        expected = {"run_id", "graph", "inputs", "metadata", "budget", "created_at"}
        if set(value) != expected:
            raise HarnessValidationError(
                "run specification fields do not match the versioned contract"
            )
        inputs = value["inputs"]
        metadata = value["metadata"]
        budget = value["budget"]
        if not isinstance(inputs, Mapping) or not isinstance(metadata, Mapping):
            raise HarnessValidationError(
                "run specification inputs and metadata must be objects"
            )
        if not isinstance(budget, Mapping):
            raise HarnessValidationError("run specification budget must be an object")
        created_at = parse_datetime(value["created_at"])
        if created_at is None:
            raise HarnessValidationError("run specification created_at is required")
        try:
            actual_budget = HarnessBudget(**dict(budget))
        except TypeError as exc:
            raise HarnessValidationError("run specification budget is invalid") from exc
        return cls(
            run_id=value["run_id"],
            graph=HarnessGraphDefinition.from_dict(value["graph"]),
            inputs=dict(inputs),
            metadata=dict(metadata),
            budget=actual_budget,
            created_at=created_at,
        )


def run_spec_checksum(run_spec: HarnessRunSpec) -> str:
    """Return the checksum of the immutable Graph run specification."""

    if not isinstance(run_spec, HarnessRunSpec):
        raise TypeError("run_spec must be HarnessRunSpec")
    return checksum_for(run_spec.to_dict())


__all__ = [
    "HarnessRunSpec",
    "HarnessRunStatus",
    "HarnessStepStatus",
    "run_spec_checksum",
]
