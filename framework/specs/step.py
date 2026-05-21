"""Declarative workflow step specification models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
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
    SKILL = "skill"

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
        if self.step_type == StepType.SKILL:
            _normalize_skill_step_instance(self)

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
        return cls(**_normalize_step_payload(payload))


_TEMPLATE_REF_PATTERN = re.compile(r"^\s*\{\{\s*(?P<key>[^{}]+?)\s*\}\}\s*$")


def normalize_step_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize external workflow step aliases into the canonical StepSpec shape."""

    return _normalize_step_payload(payload)


def _normalize_step_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    if "step_id" not in normalized and "id" in normalized:
        normalized["step_id"] = normalized.pop("id")
    else:
        normalized.pop("id", None)
    if "step_type" not in normalized and "type" in normalized:
        normalized["step_type"] = normalized.pop("type")
    else:
        normalized.pop("type", None)

    try:
        step_type = StepType.from_value(normalized.get("step_type", StepType.FUNCTION))
    except ValueError:
        return normalized

    if step_type == StepType.SKILL:
        _normalize_skill_step_payload(normalized)

    return normalized


def _normalize_skill_step_payload(payload: dict[str, Any]) -> None:
    metadata = dict(payload.get("metadata") or {})

    if "skill" in payload:
        skill_name = payload.pop("skill")
        metadata.setdefault("skill", skill_name)
        payload.setdefault("implementation", str(skill_name or ""))

    if "input" in payload:
        metadata.setdefault("input", payload.pop("input"))
    metadata.setdefault("input", {})

    for field_name in (
        "output_key",
        "store_full_result",
        "store_output",
        "fail_workflow_on_error",
        "timeout_seconds",
    ):
        if field_name in payload:
            metadata.setdefault(field_name, payload.pop(field_name))

    if "retry" in payload:
        payload.setdefault("retry", payload.pop("retry"))

    timeout_seconds = metadata.get("timeout_seconds")
    if _is_positive_int(timeout_seconds) and "timeout" not in payload and "timeout_policy" not in payload:
        payload["timeout"] = {"timeout_seconds": timeout_seconds}

    step_id = str(payload.get("step_id") or "")
    read_keys = set(str(key) for key in payload.get("read_keys") or [])
    read_keys.update(_template_keys(metadata.get("input") or {}))
    payload["read_keys"] = sorted(read_keys)

    write_keys = set(str(key) for key in payload.get("write_keys") or [])
    if step_id and metadata.get("store_full_result", True):
        write_keys.add(f"{step_id}.result")
    if step_id and metadata.get("store_output", True):
        write_keys.add(f"{step_id}.output")
    output_key = metadata.get("output_key")
    if output_key is not None:
        write_keys.add(str(output_key))
    payload["write_keys"] = sorted(write_keys)
    payload["metadata"] = metadata


def _normalize_skill_step_instance(step: StepSpec) -> None:
    metadata = dict(step.metadata)
    if not step.implementation and metadata.get("skill") is not None:
        object.__setattr__(step, "implementation", str(metadata["skill"] or ""))
    metadata.setdefault("input", {})

    timeout_seconds = metadata.get("timeout_seconds")
    if _is_positive_int(timeout_seconds) and step.timeout is None and step.timeout_policy.timeout_seconds is None:
        object.__setattr__(
            step,
            "timeout_policy",
            TimeoutPolicySpec(timeout_seconds=float(timeout_seconds)),
        )

    read_keys = set(str(key) for key in step.read_keys)
    read_keys.update(_template_keys(metadata.get("input") or {}))
    object.__setattr__(step, "read_keys", sorted(read_keys))

    write_keys = set(str(key) for key in step.write_keys)
    if metadata.get("store_full_result", True):
        write_keys.add(f"{step.step_id}.result")
    if metadata.get("store_output", True):
        write_keys.add(f"{step.step_id}.output")
    output_key = metadata.get("output_key")
    if output_key is not None:
        write_keys.add(str(output_key))
    object.__setattr__(step, "write_keys", sorted(write_keys))
    object.__setattr__(step, "metadata", metadata)


def _template_keys(value: Any) -> set[str]:
    if isinstance(value, str):
        match = _TEMPLATE_REF_PATTERN.match(value)
        if match is None:
            return set()
        return {match.group("key").strip()}
    if isinstance(value, dict):
        keys: set[str] = set()
        for item in value.values():
            keys.update(_template_keys(item))
        return keys
    if isinstance(value, list):
        keys = set()
        for item in value:
            keys.update(_template_keys(item))
        return keys
    return set()


def _is_positive_int(value: Any) -> bool:
    return type(value) is int and value > 0


def _coerce_policy(owner: Any, field_name: str, model: type) -> None:
    value = getattr(owner, field_name)
    if not isinstance(value, model):
        object.__setattr__(owner, field_name, model(**value))


__all__ = ["StepSpec", "StepStatus", "StepType", "normalize_step_payload"]
