from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from enum import StrEnum
from typing import Any, Protocol

from framework.specs import StepSpec, StepType
from framework.workflow.buffer.data_buffer import StepScopedDataBufferView
from framework.workflow.runtime.result import StepOutcome


class StepExecutionError(RuntimeError):
    """Raised when a step cannot be executed by a runner."""


class StepRunnerCapabilityError(StepExecutionError):
    """Raised when a runner cannot honor a requested runtime capability."""


class StepRunnerResolutionError(StepExecutionError):
    """Raised when no runner can resolve a step."""


class StepRunnerSideEffectLevel(StrEnum):
    NONE = "none"
    READ_ONLY = "read_only"
    IDEMPOTENT_WRITE = "idempotent_write"
    EXTERNAL_WRITE = "external_write"
    IRREVERSIBLE = "irreversible"


@dataclass(frozen=True)
class StepRunnerCapability:
    step_type: StepType
    runner_id: str
    version: str
    supports_checkpoint: bool
    supports_resume: bool
    supports_timeout: bool
    supports_retry: bool
    side_effect_level: StepRunnerSideEffectLevel | str
    required_dependencies: list[str] = dataclass_field(default_factory=list)
    description: str | None = None
    supported_implementations: list[str] = dataclass_field(default_factory=list)

    def __post_init__(self) -> None:
        object.__setattr__(self, "step_type", StepType(self.step_type))
        object.__setattr__(
            self,
            "side_effect_level",
            StepRunnerSideEffectLevel(self.side_effect_level),
        )
        if not self.runner_id:
            raise ValueError("runner_id is required")
        if not self.version:
            raise ValueError("runner version is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_type": self.step_type.value,
            "runner_id": self.runner_id,
            "version": self.version,
            "supports_checkpoint": self.supports_checkpoint,
            "supports_resume": self.supports_resume,
            "supports_timeout": self.supports_timeout,
            "supports_retry": self.supports_retry,
            "side_effect_level": str(self.side_effect_level),
            "required_dependencies": list(self.required_dependencies),
            "description": self.description,
            "supported_implementations": list(self.supported_implementations),
        }


@dataclass(frozen=True)
class ValidationErrorItem:
    code: str
    message: str
    field: str | None = None
    details: dict[str, object] = dataclass_field(default_factory=dict)


class StepRunner(Protocol):
    capability: StepRunnerCapability

    def can_resolve(self, step: StepSpec) -> bool:
        ...

    def validate_step(self, step: StepSpec) -> list[ValidationErrorItem]:
        ...

    def run(self, step: StepSpec, buffer: StepScopedDataBufferView) -> StepOutcome:
        ...


def default_runner_can_resolve(
    capability: StepRunnerCapability,
    step: StepSpec,
) -> bool:
    if step.step_type != capability.step_type:
        return False
    if not capability.supported_implementations:
        return True
    return step.implementation in set(capability.supported_implementations)



