"""Declarative workflow step specification models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from framework.specs.policy import (
    ArtifactPolicySpec,
    FailurePolicySpec,
    LineagePolicySpec,
    QualityPolicySpec,
    ResourcePolicySpec,
    RetryPolicySpec,
    RuntimeQualityPolicySpec,
    TimeoutPolicySpec,
)
from framework.specs.validation import WorkflowSpecError


class StepType(str, Enum):
    """Workflow step runner families with stable runtime ownership boundaries."""

    FUNCTION = "function"
    TOOL = "tool"
    AGENT_LOOP = "agent_loop"
    ROUTER = "router"
    QUALITY_GATE = "quality_gate"
    PERSIST = "persist"
    ARTIFACT = "artifact"
    PARALLEL_GROUP = "parallel_group"
    JOIN = "join"
    SUBWORKFLOW = "subworkflow"
    HUMAN_REVIEW = "human_review"
    NOTIFICATION = "notification"
    TOOL_BATCH = "tool_batch"
    TOOL_CALL = "tool_call"
    MEMORY_RECALL = "memory_recall"
    MEMORY_WRITE = "memory_write"
    MEMORY_CONSOLIDATE = "memory_consolidate"
    MEMORY_INDEX = "memory_index"

    @classmethod
    def from_value(cls, value: str | StepType) -> "StepType":
        if isinstance(value, StepType):
            return value
        return cls(str(value))

    def requires_runner(self) -> bool:
        return self not in {StepType.JOIN}


class StepStatus(str, Enum):
    """Per-step execution state; do not use for workflow or worker task records."""

    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    PAUSED = "paused"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"
    RETRYING = "retrying"
    CANCELLED = "cancelled"

    def is_terminal(self) -> bool:
        from framework.workflow.runtime.status_classifier import RuntimeStatusClassifier

        return RuntimeStatusClassifier.is_terminal_step(self)


@dataclass(frozen=True)
class StepSpec:
    step_id: str
    implementation: str = ""
    step_type: StepType = StepType.FUNCTION
    name: str = ""
    description: str = ""
    read_keys: list[str] = field(default_factory=list)
    write_keys: list[str] = field(default_factory=list)
    required_output_keys: list[str] = field(default_factory=list)
    nullable_output_keys: list[str] = field(default_factory=list)
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    inputs: dict[str, str] = field(default_factory=dict)
    outputs: dict[str, str] = field(default_factory=dict)
    retry_policy: RetryPolicySpec = field(default_factory=RetryPolicySpec)
    timeout_policy: TimeoutPolicySpec = field(default_factory=TimeoutPolicySpec)
    failure_policy: FailurePolicySpec = field(default_factory=FailurePolicySpec)
    resource_policy: ResourcePolicySpec = field(default_factory=ResourcePolicySpec)
    quality_policy: QualityPolicySpec | None = None
    artifact_policy: ArtifactPolicySpec | None = None
    lineage_policy: LineagePolicySpec | None = None
    runtime_quality: RuntimeQualityPolicySpec | dict[str, Any] | None = None
    retry: RetryPolicySpec | dict[str, Any] | None = None
    timeout: TimeoutPolicySpec | dict[str, Any] | None = None
    resource: ResourcePolicySpec | dict[str, Any] | None = None
    quality: QualityPolicySpec | dict[str, Any] | None = None
    idempotent: bool = True
    cacheable: bool = False
    client_facing: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "step_type", StepType.from_value(self.step_type))
        if not self.implementation:
            config_implementation = self.config.get("implementation")
            object.__setattr__(self, "implementation", str(config_implementation or ""))
        if self.retry is not None:
            object.__setattr__(self, "retry_policy", self.retry)
        if self.timeout is not None:
            object.__setattr__(self, "timeout_policy", self.timeout)
        if self.resource is not None:
            object.__setattr__(self, "resource_policy", self.resource)
        if self.quality is not None:
            object.__setattr__(self, "quality_policy", self.quality)
        _coerce_policy(self, "retry_policy", RetryPolicySpec)
        _coerce_policy(self, "timeout_policy", TimeoutPolicySpec)
        _coerce_policy(self, "failure_policy", FailurePolicySpec)
        _coerce_policy(self, "resource_policy", ResourcePolicySpec)
        if self.quality_policy is not None and not isinstance(
            self.quality_policy, QualityPolicySpec
        ):
            object.__setattr__(
                self,
                "quality_policy",
                QualityPolicySpec(**self.quality_policy),
            )
        if self.artifact_policy is not None and not isinstance(
            self.artifact_policy, ArtifactPolicySpec
        ):
            object.__setattr__(
                self,
                "artifact_policy",
                ArtifactPolicySpec(**self.artifact_policy),
            )
        if self.lineage_policy is not None and not isinstance(
            self.lineage_policy, LineagePolicySpec
        ):
            object.__setattr__(
                self,
                "lineage_policy",
                LineagePolicySpec(**self.lineage_policy),
            )
        if self.runtime_quality is not None and not isinstance(
            self.runtime_quality, RuntimeQualityPolicySpec
        ):
            object.__setattr__(
                self,
                "runtime_quality",
                RuntimeQualityPolicySpec(**self.runtime_quality),
            )
        if not self.step_id:
            raise WorkflowSpecError("step_id is required")
        if not isinstance(self.input_schema, dict):
            raise WorkflowSpecError(f"input_schema must be an object for step {self.step_id}")
        if not isinstance(self.output_schema, dict):
            raise WorkflowSpecError(f"output_schema must be an object for step {self.step_id}")
        if not isinstance(self.config, dict):
            raise WorkflowSpecError(f"config must be an object for step {self.step_id}")
        if not isinstance(self.inputs, dict):
            raise WorkflowSpecError(f"inputs must be an object for step {self.step_id}")
        if not isinstance(self.outputs, dict):
            raise WorkflowSpecError(f"outputs must be an object for step {self.step_id}")

    def input_keys(self) -> set[str]:
        return {*self.read_keys, *self.inputs.keys()}

    def output_keys(self) -> set[str]:
        return {*self.write_keys, *self.outputs.keys()}

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "step_id": self.step_id,
            "name": self.name,
            "description": self.description,
            "step_type": self.step_type.value,
            "implementation": self.implementation,
            "read_keys": list(self.read_keys),
            "write_keys": list(self.write_keys),
            "required_output_keys": list(self.required_output_keys),
            "nullable_output_keys": list(self.nullable_output_keys),
            "input_schema": dict(self.input_schema),
            "output_schema": dict(self.output_schema),
            "retry_policy": self.retry_policy.to_dict(),
            "timeout_policy": self.timeout_policy.to_dict(),
            "failure_policy": self.failure_policy.to_dict(),
            "resource_policy": self.resource_policy.to_dict(),
            "quality_policy": (
                self.quality_policy.to_dict() if self.quality_policy is not None else None
            ),
            "artifact_policy": (
                self.artifact_policy.to_dict() if self.artifact_policy is not None else None
            ),
            "lineage_policy": (
                self.lineage_policy.to_dict() if self.lineage_policy is not None else None
            ),
            "runtime_quality": (
                self.runtime_quality.to_dict() if self.runtime_quality is not None else None
            ),
            "idempotent": self.idempotent,
            "cacheable": self.cacheable,
            "client_facing": self.client_facing,
            "metadata": dict(self.metadata),
        }
        if self.config:
            payload["config"] = dict(self.config)
        if self.inputs:
            payload["inputs"] = dict(self.inputs)
        if self.outputs:
            payload["outputs"] = dict(self.outputs)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "StepSpec":
        return cls(**payload)


def _coerce_policy(owner: Any, field_name: str, model: type) -> None:
    value = getattr(owner, field_name)
    if not isinstance(value, model):
        object.__setattr__(owner, field_name, model(**value))


__all__ = ["StepSpec", "StepStatus", "StepType"]
