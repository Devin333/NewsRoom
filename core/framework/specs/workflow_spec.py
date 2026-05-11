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
    CONDITIONAL = "conditional"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"


class WorkflowStatus(str, Enum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class RetryPolicySpec:
    max_retries: int = 0
    retry_delay_seconds: list[int] = field(default_factory=list)
    backoff_strategy: str = "fixed"
    retry_on_error_types: list[str] = field(default_factory=list)
    no_retry_on_error_types: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise WorkflowSpecError("max_retries must be non-negative")
        if any(delay < 0 for delay in self.retry_delay_seconds):
            raise WorkflowSpecError("retry_delay_seconds values must be non-negative")
        if not self.backoff_strategy:
            raise WorkflowSpecError("backoff_strategy is required")

    def should_retry(self, *, error_type: str | None) -> bool:
        actual_error_type = error_type or "StepFailed"
        if actual_error_type in set(self.no_retry_on_error_types):
            return False
        retryable_errors = set(self.retry_on_error_types)
        return not retryable_errors or actual_error_type in retryable_errors

    def delay_for_retry(self, retry_index: int) -> int:
        if not self.retry_delay_seconds:
            return 0
        index = min(max(retry_index - 1, 0), len(self.retry_delay_seconds) - 1)
        return self.retry_delay_seconds[index]

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_retries": self.max_retries,
            "retry_delay_seconds": list(self.retry_delay_seconds),
            "backoff_strategy": self.backoff_strategy,
            "retry_on_error_types": list(self.retry_on_error_types),
            "no_retry_on_error_types": list(self.no_retry_on_error_types),
        }


@dataclass(frozen=True)
class FailurePolicySpec:
    on_failure: str = "fail_workflow"
    fallback_step_id: str | None = None
    mark_as_blocked: bool = False
    allow_partial_success: bool = False

    def __post_init__(self) -> None:
        if not self.on_failure:
            raise WorkflowSpecError("on_failure is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "on_failure": self.on_failure,
            "fallback_step_id": self.fallback_step_id,
            "mark_as_blocked": self.mark_as_blocked,
            "allow_partial_success": self.allow_partial_success,
        }


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
    retry_policy: RetryPolicySpec = field(default_factory=RetryPolicySpec)
    failure_policy: FailurePolicySpec = field(default_factory=FailurePolicySpec)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "step_type", StepType(self.step_type))
        if not isinstance(self.retry_policy, RetryPolicySpec):
            object.__setattr__(self, "retry_policy", RetryPolicySpec(**self.retry_policy))
        if not isinstance(self.failure_policy, FailurePolicySpec):
            object.__setattr__(self, "failure_policy", FailurePolicySpec(**self.failure_policy))
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
            "retry_policy": self.retry_policy.to_dict(),
            "failure_policy": self.failure_policy.to_dict(),
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
        step_by_id = {step.step_id: step for step in self.steps}
        if self.start_step_id not in step_id_set:
            raise WorkflowSpecError(f"start step does not exist: {self.start_step_id}")

        for terminal_step_id in self.terminal_step_ids:
            if terminal_step_id not in step_id_set:
                raise WorkflowSpecError(f"terminal step does not exist: {terminal_step_id}")

        for step in self.steps:
            undeclared_outputs = sorted(set(step.required_output_keys) - set(step.write_keys))
            if undeclared_outputs:
                raise WorkflowSpecError(
                    f"required_output_keys must be declared in write_keys for step "
                    f"{step.step_id}: {', '.join(undeclared_outputs)}"
                )
            fallback_step_id = step.failure_policy.fallback_step_id
            if fallback_step_id is not None and fallback_step_id not in step_id_set:
                raise WorkflowSpecError(
                    f"fallback step does not exist for {step.step_id}: {fallback_step_id}"
                )

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
            if edge.condition == EdgeCondition.CONDITIONAL and not edge.condition_expr:
                raise WorkflowSpecError(
                    f"conditional edge {edge.edge_id} requires condition_expr"
                )

        adjacency = _workflow_adjacency(self)
        reachable_step_ids = _reachable_step_ids(self.start_step_id, adjacency)
        for terminal_step_id in self.terminal_step_ids:
            if terminal_step_id not in reachable_step_ids:
                raise WorkflowSpecError(f"terminal step is not reachable: {terminal_step_id}")

        reverse_adjacency = _reverse_adjacency(adjacency)
        for step in self.steps:
            if step.step_id not in reachable_step_ids:
                continue
            upstream_step_ids = _reachable_step_ids(step.step_id, reverse_adjacency) - {step.step_id}
            available_keys = {"request"}
            for upstream_step_id in upstream_step_ids:
                available_keys.update(step_by_id[upstream_step_id].write_keys)
            missing_reads = sorted(set(step.read_keys) - available_keys)
            if missing_reads:
                raise WorkflowSpecError(
                    f"read_keys are not produced by upstream steps for step "
                    f"{step.step_id}: {', '.join(missing_reads)}"
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


def _workflow_adjacency(workflow: WorkflowSpec) -> dict[str, set[str]]:
    adjacency = {step.step_id: set() for step in workflow.steps}
    for edge in workflow.edges:
        adjacency[edge.source_step_id].add(edge.target_step_id)
    for step in workflow.steps:
        fallback_step_id = step.failure_policy.fallback_step_id
        if fallback_step_id is not None:
            adjacency[step.step_id].add(fallback_step_id)
    return adjacency


def _reverse_adjacency(adjacency: dict[str, set[str]]) -> dict[str, set[str]]:
    reverse = {step_id: set() for step_id in adjacency}
    for source_step_id, target_step_ids in adjacency.items():
        for target_step_id in target_step_ids:
            reverse[target_step_id].add(source_step_id)
    return reverse


def _reachable_step_ids(start_step_id: str, adjacency: dict[str, set[str]]) -> set[str]:
    reachable: set[str] = set()
    stack = [start_step_id]
    while stack:
        step_id = stack.pop()
        if step_id in reachable:
            continue
        reachable.add(step_id)
        stack.extend(sorted(adjacency.get(step_id, set()) - reachable, reverse=True))
    return reachable
