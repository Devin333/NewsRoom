from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.shared.json import to_jsonable


class HarnessWorkerType(StrEnum):
    LLM = "llm"
    SKILL = "skill"
    SKILL_EVOLUTION = "skill_evolution"
    SUBAGENT = "subagent"
    RETRIEVAL = "retrieval"
    MEMORY = "memory"
    MCP = "mcp"
    QUALITY_GATE = "quality_gate"
    ARTIFACT = "artifact"
    SCRIPT = "script"


@dataclass(frozen=True)
class HarnessRetryPolicy:
    max_retries: int = 0
    max_attempts: int | None = None
    retry_on_statuses: tuple[str, ...] = ("failed",)
    backoff_seconds: float = 0.0
    repair_step_id: str | None = None
    fail_fast_error_types: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise HarnessValidationError("max_retries must not be negative")
        if self.max_attempts is not None and self.max_attempts < 1:
            raise HarnessValidationError("max_attempts must be greater than zero")
        if self.backoff_seconds < 0:
            raise HarnessValidationError("backoff_seconds must not be negative")
        if self.repair_step_id is not None and not str(self.repair_step_id).strip():
            raise HarnessValidationError("repair_step_id must not be blank")
        object.__setattr__(self, "retry_on_statuses", tuple(str(status) for status in self.retry_on_statuses))
        object.__setattr__(
            self,
            "fail_fast_error_types",
            tuple(str(error_type) for error_type in self.fail_fast_error_types),
        )

    @property
    def effective_max_attempts(self) -> int:
        if self.max_attempts is not None:
            return self.max_attempts
        return self.max_retries + 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_retries": self.max_retries,
            "max_attempts": self.max_attempts,
            "effective_max_attempts": self.effective_max_attempts,
            "retry_on_statuses": list(self.retry_on_statuses),
            "backoff_seconds": self.backoff_seconds,
            "repair_step_id": self.repair_step_id,
            "fail_fast_error_types": list(self.fail_fast_error_types),
        }


@dataclass(frozen=True)
class HarnessStepSpec:
    step_id: str
    worker_type: HarnessWorkerType | str
    input_keys: tuple[str, ...] = ()
    output_key: str | None = None
    retry_policy: HarnessRetryPolicy = field(default_factory=HarnessRetryPolicy)
    quality_gate: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        step_id = str(self.step_id).strip()
        if not step_id:
            raise HarnessValidationError("step_id is required")
        object.__setattr__(self, "step_id", step_id)
        object.__setattr__(self, "worker_type", HarnessWorkerType(self.worker_type))
        object.__setattr__(self, "input_keys", tuple(str(key) for key in self.input_keys))
        if self.output_key is not None and not str(self.output_key).strip():
            raise HarnessValidationError("output_key must not be blank")
        if not isinstance(self.retry_policy, HarnessRetryPolicy):
            raise HarnessValidationError("retry_policy must be HarnessRetryPolicy")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "worker_type": self.worker_type.value,
            "input_keys": list(self.input_keys),
            "output_key": self.output_key,
            "retry_policy": self.retry_policy.to_dict(),
            "quality_gate": self.quality_gate,
            "metadata": to_jsonable(self.metadata),
        }


__all__ = ["HarnessRetryPolicy", "HarnessStepSpec", "HarnessWorkerType"]
