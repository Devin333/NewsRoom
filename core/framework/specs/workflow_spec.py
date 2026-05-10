from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class WorkflowSpecError(ValueError):
    """Raised when a workflow specification is invalid."""


class StepType(str, Enum):
    FUNCTION = "function"
    AGENT_LOOP = "agent_loop"
    ARTIFACT = "artifact"
    PERSIST = "persist"
    QUALITY_GATE = "quality_gate"


class EdgeCondition(str, Enum):
    ALWAYS = "always"
    ON_SUCCESS = "on_success"
    ON_FAILURE = "on_failure"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowStatus(str, Enum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class StepSpec:
    step_id: str
    implementation: str
    step_type: StepType = StepType.FUNCTION
    name: str = ""
    description: str = ""
    read_keys: list[str] = field(default_factory=list)
    write_keys: list[str] = field(default_factory=list)
    required_output_keys: list[str] = field(default_factory=list)
    nullable_output_keys: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "step_type", StepType(self.step_type))
        if not self.step_id:
            raise WorkflowSpecError("step_id is required")
        if not self.implementation:
            raise WorkflowSpecError(f"implementation is required for step {self.step_id}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "name": self.name,
            "description": self.description,
            "step_type": self.step_type.value,
            "implementation": self.implementation,
            "read_keys": list(self.read_keys),
            "write_keys": list(self.write_keys),
            "required_output_keys": list(self.required_output_keys),
            "nullable_output_keys": list(self.nullable_output_keys),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class EdgeSpec:
    edge_id: str
    source_step_id: str
    target_step_id: str
    condition: EdgeCondition = EdgeCondition.ON_SUCCESS
    condition_expr: str | None = None
    priority: int = 0
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "condition", EdgeCondition(self.condition))
        if not self.edge_id:
            raise WorkflowSpecError("edge_id is required")
        if not self.source_step_id:
            raise WorkflowSpecError(f"source_step_id is required for edge {self.edge_id}")
        if not self.target_step_id:
            raise WorkflowSpecError(f"target_step_id is required for edge {self.edge_id}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source_step_id": self.source_step_id,
            "target_step_id": self.target_step_id,
            "condition": self.condition.value,
            "condition_expr": self.condition_expr,
            "priority": self.priority,
            "description": self.description,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class WorkflowSpec:
    workflow_id: str
    name: str
    version: str
    start_step_id: str
    steps: list[StepSpec]
    edges: list[EdgeSpec] = field(default_factory=list)
    description: str = ""
    terminal_step_ids: list[str] = field(default_factory=list)
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.workflow_id:
            raise WorkflowSpecError("workflow_id is required")
        if not self.version:
            raise WorkflowSpecError(f"version is required for workflow {self.workflow_id}")
        if not self.steps:
            raise WorkflowSpecError(f"workflow {self.workflow_id} must define at least one step")

        step_ids = [step.step_id for step in self.steps]
        duplicate_ids = sorted({step_id for step_id in step_ids if step_ids.count(step_id) > 1})
        if duplicate_ids:
            raise WorkflowSpecError(f"duplicate step ids: {', '.join(duplicate_ids)}")

        step_id_set = set(step_ids)
        if self.start_step_id not in step_id_set:
            raise WorkflowSpecError(f"start step does not exist: {self.start_step_id}")

        for terminal_step_id in self.terminal_step_ids:
            if terminal_step_id not in step_id_set:
                raise WorkflowSpecError(f"terminal step does not exist: {terminal_step_id}")

        edge_ids = [edge.edge_id for edge in self.edges]
        duplicate_edge_ids = sorted({edge_id for edge_id in edge_ids if edge_ids.count(edge_id) > 1})
        if duplicate_edge_ids:
            raise WorkflowSpecError(f"duplicate edge ids: {', '.join(duplicate_edge_ids)}")

        for edge in self.edges:
            if edge.source_step_id not in step_id_set:
                raise WorkflowSpecError(
                    f"edge {edge.edge_id} references missing source step {edge.source_step_id}"
                )
            if edge.target_step_id not in step_id_set:
                raise WorkflowSpecError(
                    f"edge {edge.edge_id} references missing target step {edge.target_step_id}"
                )

    def step_by_id(self, step_id: str) -> StepSpec:
        for step in self.steps:
            if step.step_id == step_id:
                return step
        raise WorkflowSpecError(f"step does not exist: {step_id}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "start_step_id": self.start_step_id,
            "terminal_step_ids": list(self.terminal_step_ids),
            "steps": [step.to_dict() for step in self.steps],
            "edges": [edge.to_dict() for edge in self.edges],
            "input_schema": dict(self.input_schema),
            "output_schema": dict(self.output_schema),
            "metadata": dict(self.metadata),
        }
