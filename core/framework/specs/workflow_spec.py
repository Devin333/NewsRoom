from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class WorkflowSpecError(ValueError):
    """Raised when a workflow specification is invalid."""


class StepType(str, Enum):
    """Workflow step runner families with stable runtime ownership boundaries."""

    FUNCTION = "function"  # Deterministic Python function registered in FunctionStepRegistry.
    AGENT_LOOP = "agent_loop"  # AgentLoop execution; LLM/tool iteration stays outside executor.
    ROUTER = "router"  # Deterministic route selection that emits a next_hint.
    QUALITY_GATE = "quality_gate"  # Runtime quality decision step; publish decisions remain policy driven.
    PERSIST = "persist"  # Persistence side-effect step backed by the tool runtime.
    ARTIFACT = "artifact"  # Writes workflow artifacts through ArtifactManager.
    PARALLEL_GROUP = "parallel_group"  # In-step function fan-out with namespaced branch outputs.
    JOIN = "join"  # Fan-in summary over declared inputs and branch outcomes.
    SUBWORKFLOW = "subworkflow"  # Child WorkflowSpec execution in a separate child run.
    HUMAN_REVIEW = "human_review"  # Pause/resume boundary for human approval or review.
    NOTIFICATION = "notification"  # Notification side-effect step backed by the tool runtime.
    TOOL_BATCH = "tool_batch"  # Batched tool calls with tool-runtime policy enforcement.
    TOOL_CALL = "tool_call"  # Single tool call with tool-runtime policy enforcement.
    MEMORY_RECALL = "memory_recall"  # Direct MemoryRuntime recall step.
    MEMORY_WRITE = "memory_write"  # Direct MemoryRuntime write step.
    MEMORY_CONSOLIDATE = "memory_consolidate"  # Direct MemoryRuntime consolidation step.
    MEMORY_INDEX = "memory_index"  # Memory indexing side-effect backed by the tool runtime.


class EdgeCondition(str, Enum):
    ALWAYS = "always"
    ON_SUCCESS = "on_success"
    ON_FAILURE = "on_failure"
    CONDITIONAL = "conditional"
    LLM_DECIDE = "llm_decide"
    QUALITY_PASS = "quality_pass"
    QUALITY_REWRITE_REQUIRED = "quality_rewrite_required"
    QUALITY_BLOCKED = "quality_blocked"
    HUMAN_APPROVED = "human_approved"
    HUMAN_REJECTED = "human_rejected"
    BUDGET_EXCEEDED = "budget_exceeded"
    SOURCE_UNAVAILABLE = "source_unavailable"


class StepStatus(str, Enum):
    """Per-step execution state; do not use for workflow or worker task records."""

    PENDING = "pending"  # Step is defined but not yet scheduled in this workflow run.
    READY = "ready"  # Step is scheduled and ready for execution.
    RUNNING = "running"  # Step attempt is currently executing.
    SUCCEEDED = "succeeded"  # Step completed and its declared outputs are available.
    FAILED = "failed"  # Step failed and may route through retry or failure policy.
    BLOCKED = "blocked"  # Step cannot proceed without an external/configuration fix.
    PAUSED = "paused"  # Step intentionally paused and may resume from checkpoint.
    TIMEOUT = "timeout"  # Step attempt exceeded its timeout policy.
    SKIPPED = "skipped"  # Step was intentionally bypassed by routing or policy.
    RETRYING = "retrying"  # Step has a retry scheduled; persisted only as an intermediate signal.
    CANCELLED = "cancelled"  # Step was cancelled by operator or enclosing workflow.


class WorkflowStatus(str, Enum):
    """Workflow run state; separate from StepStatus and worker TaskStatus."""

    CREATED = "created"  # Run has been created but execution has not started.
    RUNNING = "running"  # Workflow executor is actively processing scheduled steps.
    PAUSED = "paused"  # Workflow is paused at a non-human checkpoint.
    WAITING_FOR_HUMAN = "waiting_for_human"  # Workflow is paused for human review/approval.
    RETRYING = "retrying"  # Workflow has retry work scheduled; not a worker task status.
    SUCCEEDED = "succeeded"  # Workflow reached a terminal successful state.
    FAILED = "failed"  # Workflow reached a terminal failure state.
    BLOCKED = "blocked"  # Workflow cannot proceed without an external/configuration fix.
    CANCELLED = "cancelled"  # Workflow was cancelled before normal terminal completion.
    BUDGET_EXCEEDED = "budget_exceeded"  # Workflow stopped because global/runtime budget was exhausted.


@dataclass(frozen=True)
class ValidationErrorItem:
    code: str
    message: str
    step_id: str | None = None
    edge_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "step_id": self.step_id,
            "edge_id": self.edge_id,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ValidationWarningItem:
    code: str
    message: str
    step_id: str | None = None
    edge_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "step_id": self.step_id,
            "edge_id": self.edge_id,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    errors: list[ValidationErrorItem] = field(default_factory=list)
    warnings: list[ValidationWarningItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "errors": [error.to_dict() for error in self.errors],
            "warnings": [warning.to_dict() for warning in self.warnings],
        }


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
class TimeoutPolicySpec:
    timeout_seconds: float | None = None
    on_timeout: str = "fail"

    def __post_init__(self) -> None:
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise WorkflowSpecError("timeout_seconds must be positive when set")
        if self.on_timeout not in {"fail", "retry"}:
            raise WorkflowSpecError("on_timeout must be one of: fail, retry")

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeout_seconds": self.timeout_seconds,
            "on_timeout": self.on_timeout,
        }


@dataclass(frozen=True)
class ResourcePolicySpec:
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    max_cost_usd: float | None = None
    max_items: int | None = None
    max_parallelism: int | None = None
    max_artifact_bytes: int | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "max_input_tokens",
            "max_output_tokens",
            "max_items",
            "max_parallelism",
            "max_artifact_bytes",
        ):
            value = getattr(self, field_name)
            if value is not None and value < 0:
                raise WorkflowSpecError(f"{field_name} must be non-negative when set")
        if self.max_cost_usd is not None and self.max_cost_usd < 0:
            raise WorkflowSpecError("max_cost_usd must be non-negative when set")

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "max_cost_usd": self.max_cost_usd,
            "max_items": self.max_items,
            "max_parallelism": self.max_parallelism,
            "max_artifact_bytes": self.max_artifact_bytes,
        }


@dataclass(frozen=True)
class QualityPolicySpec:
    min_citation_coverage: float | None = None
    min_editor_score: float | None = None
    block_on_unsupported_claims: bool = True
    allow_rewrite_count: int = 1

    def __post_init__(self) -> None:
        for field_name in ("min_citation_coverage", "min_editor_score"):
            value = getattr(self, field_name)
            if value is not None and not 0 <= value <= 1:
                raise WorkflowSpecError(f"{field_name} must be between 0 and 1 when set")
        if self.allow_rewrite_count < 0:
            raise WorkflowSpecError("allow_rewrite_count must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_citation_coverage": self.min_citation_coverage,
            "min_editor_score": self.min_editor_score,
            "block_on_unsupported_claims": self.block_on_unsupported_claims,
            "allow_rewrite_count": self.allow_rewrite_count,
        }


@dataclass(frozen=True)
class ArtifactPolicySpec:
    write_step_input: bool = False
    write_step_output: bool = False
    write_step_error: bool = True
    redacted: bool = True
    artifact_types: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "write_step_input": self.write_step_input,
            "write_step_output": self.write_step_output,
            "write_step_error": self.write_step_error,
            "redacted": self.redacted,
            "artifact_types": list(self.artifact_types),
        }


@dataclass(frozen=True)
class LineagePolicySpec:
    enabled: bool = True
    input_keys: list[str] = field(default_factory=list)
    output_keys: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "input_keys": list(self.input_keys),
            "output_keys": list(self.output_keys),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class WorkflowTriggerSpec:
    trigger_type: str = "manual"
    schedule: str | None = None
    event_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.trigger_type:
            raise WorkflowSpecError("trigger_type is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "trigger_type": self.trigger_type,
            "schedule": self.schedule,
            "event_type": self.event_type,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class WorkflowPolicySpec:
    retry_policy: RetryPolicySpec = field(default_factory=RetryPolicySpec)
    timeout_policy: TimeoutPolicySpec = field(default_factory=TimeoutPolicySpec)
    failure_policy: FailurePolicySpec = field(default_factory=FailurePolicySpec)
    resource_policy: ResourcePolicySpec = field(default_factory=ResourcePolicySpec)
    quality_policy: QualityPolicySpec | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "retry_policy": self.retry_policy.to_dict(),
            "timeout_policy": self.timeout_policy.to_dict(),
            "failure_policy": self.failure_policy.to_dict(),
            "resource_policy": self.resource_policy.to_dict(),
            "quality_policy": (
                self.quality_policy.to_dict() if self.quality_policy is not None else None
            ),
            "metadata": dict(self.metadata),
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
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    retry_policy: RetryPolicySpec = field(default_factory=RetryPolicySpec)
    timeout_policy: TimeoutPolicySpec = field(default_factory=TimeoutPolicySpec)
    failure_policy: FailurePolicySpec = field(default_factory=FailurePolicySpec)
    resource_policy: ResourcePolicySpec = field(default_factory=ResourcePolicySpec)
    quality_policy: QualityPolicySpec | None = None
    artifact_policy: ArtifactPolicySpec | None = None
    lineage_policy: LineagePolicySpec | None = None
    idempotent: bool = True
    cacheable: bool = False
    client_facing: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "step_type", StepType(self.step_type))
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
        if not self.step_id:
            raise WorkflowSpecError("step_id is required")
        if not self.implementation:
            raise WorkflowSpecError(f"implementation is required for step {self.step_id}")
        if not isinstance(self.input_schema, dict):
            raise WorkflowSpecError(f"input_schema must be an object for step {self.step_id}")
        if not isinstance(self.output_schema, dict):
            raise WorkflowSpecError(f"output_schema must be an object for step {self.step_id}")

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
            "idempotent": self.idempotent,
            "cacheable": self.cacheable,
            "client_facing": self.client_facing,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class EdgeSpec:
    edge_id: str
    source_step_id: str
    target_step_id: str
    condition: EdgeCondition = EdgeCondition.ON_SUCCESS
    condition_expr: str | None = None
    input_mapping: dict[str, str] = field(default_factory=dict)
    output_mapping: dict[str, str] = field(default_factory=dict)
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
        if not isinstance(self.input_mapping, dict):
            raise WorkflowSpecError(f"input_mapping must be an object for edge {self.edge_id}")
        if not isinstance(self.output_mapping, dict):
            raise WorkflowSpecError(f"output_mapping must be an object for edge {self.edge_id}")

    def to_dict(self) -> dict[str, Any]:
        return {
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


@dataclass(frozen=True)
class WorkflowSpec:
    workflow_id: str
    name: str
    version: str
    start_step_id: str
    steps: list[StepSpec]
    edges: list[EdgeSpec] = field(default_factory=list)
    description: str = ""
    trigger: WorkflowTriggerSpec | None = None
    terminal_step_ids: list[str] = field(default_factory=list)
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    policies: WorkflowPolicySpec = field(default_factory=WorkflowPolicySpec)
    max_step_visits: int = 100
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.trigger is not None and not isinstance(self.trigger, WorkflowTriggerSpec):
            object.__setattr__(self, "trigger", WorkflowTriggerSpec(**self.trigger))
        if not isinstance(self.policies, WorkflowPolicySpec):
            object.__setattr__(self, "policies", WorkflowPolicySpec(**self.policies))
        object.__setattr__(
            self,
            "steps",
            [step if isinstance(step, StepSpec) else StepSpec(**step) for step in self.steps],
        )
        object.__setattr__(
            self,
            "edges",
            [edge if isinstance(edge, EdgeSpec) else EdgeSpec(**edge) for edge in self.edges],
        )
        if not isinstance(self.input_schema, dict):
            raise WorkflowSpecError(f"input_schema must be an object for workflow {self.workflow_id}")
        if not isinstance(self.output_schema, dict):
            raise WorkflowSpecError(f"output_schema must be an object for workflow {self.workflow_id}")

    def validate(
        self,
        *,
        request_keys: list[str] | None = None,
        registered_step_types: list[StepType | str] | None = None,
        strict: bool = False,
        checkpoint_store_available: bool = False,
        allow_pause_artifact_strategy: bool = False,
    ) -> None:
        result = self.validation_result(
            request_keys=request_keys,
            registered_step_types=registered_step_types,
            strict=strict,
            checkpoint_store_available=checkpoint_store_available,
            allow_pause_artifact_strategy=allow_pause_artifact_strategy,
        )
        if not result.passed:
            raise WorkflowSpecError(result.errors[0].message)

    def validation_result(
        self,
        *,
        request_keys: list[str] | None = None,
        registered_step_types: list[StepType | str] | None = None,
        strict: bool = False,
        checkpoint_store_available: bool = False,
        allow_pause_artifact_strategy: bool = False,
    ) -> ValidationResult:
        errors: list[ValidationErrorItem] = []
        warnings: list[ValidationWarningItem] = []

        def add_error(
            code: str,
            message: str,
            *,
            step_id: str | None = None,
            edge_id: str | None = None,
            metadata: dict[str, Any] | None = None,
        ) -> None:
            errors.append(
                ValidationErrorItem(
                    code=code,
                    message=message,
                    step_id=step_id,
                    edge_id=edge_id,
                    metadata=metadata or {},
                )
            )

        def add_warning(
            code: str,
            message: str,
            *,
            step_id: str | None = None,
            edge_id: str | None = None,
            metadata: dict[str, Any] | None = None,
        ) -> None:
            warnings.append(
                ValidationWarningItem(
                    code=code,
                    message=message,
                    step_id=step_id,
                    edge_id=edge_id,
                    metadata=metadata or {},
                )
            )

        if not self.workflow_id:
            add_error("workflow_id_required", "workflow_id is required")
        if not self.version:
            add_error(
                "version_required",
                f"version is required for workflow {self.workflow_id}",
            )
        if not self.steps:
            add_error(
                "steps_required",
                f"workflow {self.workflow_id} must define at least one step",
            )
        if self.max_step_visits <= 0:
            add_error("max_step_visits_invalid", "max_step_visits must be positive")

        step_ids = [step.step_id for step in self.steps]
        duplicate_ids = sorted({step_id for step_id in step_ids if step_ids.count(step_id) > 1})
        if duplicate_ids:
            add_error("duplicate_step_ids", f"duplicate step ids: {', '.join(duplicate_ids)}")

        step_id_set = set(step_ids)
        step_by_id = {step.step_id: step for step in self.steps}
        if step_id_set and self.start_step_id not in step_id_set:
            add_error(
                "start_step_missing",
                f"start step does not exist: {self.start_step_id}",
                step_id=self.start_step_id,
            )

        for terminal_step_id in self.terminal_step_ids:
            if terminal_step_id not in step_id_set:
                add_error(
                    "terminal_step_missing",
                    f"terminal step does not exist: {terminal_step_id}",
                    step_id=terminal_step_id,
                )

        for step in self.steps:
            if strict and step.step_type == StepType.HUMAN_REVIEW:
                has_pause_strategy = (
                    allow_pause_artifact_strategy
                    or _human_review_has_pause_artifact_strategy(step)
                )
                if not checkpoint_store_available and not has_pause_strategy:
                    add_error(
                        "human_review_checkpoint_required",
                        "human_review step requires checkpoint_store or pause artifact strategy "
                        f"in strict mode: {step.step_id}",
                        step_id=step.step_id,
                    )
            undeclared_outputs = sorted(set(step.required_output_keys) - set(step.write_keys))
            if undeclared_outputs:
                add_error(
                    "required_outputs_undeclared",
                    f"required_output_keys must be declared in write_keys for step "
                    f"{step.step_id}: {', '.join(undeclared_outputs)}",
                    step_id=step.step_id,
                )
            fallback_step_id = step.failure_policy.fallback_step_id
            if fallback_step_id is not None and fallback_step_id not in step_id_set:
                add_error(
                    "fallback_step_missing",
                    f"fallback step does not exist for {step.step_id}: {fallback_step_id}",
                    step_id=step.step_id,
                )
            for secret_path in _secret_paths(step.to_dict()):
                add_warning(
                    "secret_like_spec_field",
                    f"secret-like field appears in step spec: {secret_path}",
                    step_id=step.step_id,
                    metadata={"path": secret_path},
                )

        if registered_step_types is not None:
            available = {StepType(step_type) for step_type in registered_step_types}
            for step in self.steps:
                if step.step_type not in available:
                    add_error(
                        "step_runner_missing",
                        f"step runner is not registered: {step.step_type.value}",
                        step_id=step.step_id,
                    )

        edge_ids = [edge.edge_id for edge in self.edges]
        duplicate_edge_ids = sorted({edge_id for edge_id in edge_ids if edge_ids.count(edge_id) > 1})
        if duplicate_edge_ids:
            add_error(
                "duplicate_edge_ids",
                f"duplicate edge ids: {', '.join(duplicate_edge_ids)}",
            )

        for edge in self.edges:
            if edge.source_step_id not in step_id_set:
                add_error(
                    "edge_source_missing",
                    f"edge {edge.edge_id} references missing source step {edge.source_step_id}",
                    edge_id=edge.edge_id,
                )
            if edge.target_step_id not in step_id_set:
                add_error(
                    "edge_target_missing",
                    f"edge {edge.edge_id} references missing target step {edge.target_step_id}",
                    edge_id=edge.edge_id,
                )
            if edge.condition == EdgeCondition.CONDITIONAL and not edge.condition_expr:
                add_error(
                    "conditional_expression_missing",
                    f"conditional edge {edge.edge_id} requires condition_expr",
                    edge_id=edge.edge_id,
                )
            if edge.condition == EdgeCondition.LLM_DECIDE and _llm_decide_is_governance_edge(edge):
                add_error(
                    "llm_decide_governance_forbidden",
                    f"LLM_DECIDE edge {edge.edge_id} cannot control safety, approval, "
                    "quality pass, or publish decisions",
                    edge_id=edge.edge_id,
                    metadata={"target_step_id": edge.target_step_id},
                )
            for secret_path in _secret_paths(edge.to_dict()):
                add_warning(
                    "secret_like_spec_field",
                    f"secret-like field appears in edge spec: {secret_path}",
                    edge_id=edge.edge_id,
                    metadata={"path": secret_path},
                )

        for secret_path in _secret_paths({"metadata": self.metadata}):
            add_warning(
                "secret_like_spec_field",
                f"secret-like field appears in workflow spec: {secret_path}",
                metadata={"path": secret_path},
            )

        if errors:
            return ValidationResult(passed=False, errors=errors, warnings=warnings)

        adjacency = _workflow_adjacency(self)
        reachable_step_ids = _reachable_step_ids(self.start_step_id, adjacency)
        for terminal_step_id in self.terminal_step_ids:
            if terminal_step_id not in reachable_step_ids:
                add_error(
                    "terminal_step_unreachable",
                    f"terminal step is not reachable: {terminal_step_id}",
                    step_id=terminal_step_id,
                )

        reverse_adjacency = _reverse_adjacency(adjacency)
        initial_keys = set(request_keys or ["request"])
        input_properties = self.input_schema.get("properties")
        if isinstance(input_properties, dict):
            initial_keys.update(str(key) for key in input_properties)
        initial_keys.update(str(key) for key in self.metadata.get("initial_keys", []))
        for step in self.steps:
            if step.step_id not in reachable_step_ids:
                add_warning(
                    "step_unreachable",
                    f"step is not reachable from start step: {step.step_id}",
                    step_id=step.step_id,
                )
                continue
            upstream_step_ids = _reachable_step_ids(step.step_id, reverse_adjacency) - {step.step_id}
            available_keys = set(initial_keys)
            for upstream_step_id in upstream_step_ids:
                available_keys.update(step_by_id[upstream_step_id].write_keys)
            missing_reads = sorted(set(step.read_keys) - available_keys)
            if missing_reads:
                add_error(
                    "read_keys_unavailable",
                    f"read_keys are not produced by upstream steps for step "
                    f"{step.step_id}: {', '.join(missing_reads)}",
                    step_id=step.step_id,
                )
            if strict:
                missing_strict_reads = sorted(
                    set(step.read_keys)
                    - _strict_keys_available_before_step(
                        workflow=self,
                        target_step_id=step.step_id,
                        initial_keys=initial_keys,
                    )
                )
                if missing_strict_reads:
                    add_error(
                        "read_keys_not_available_on_all_paths",
                        f"read_keys are not available on every path before step "
                        f"{step.step_id}: {', '.join(missing_strict_reads)}",
                        step_id=step.step_id,
                    )
        _validate_parallel_write_conflicts(
            workflow=self,
            add_error=add_error,
            strict=strict,
        )
        return ValidationResult(passed=not errors, errors=errors, warnings=warnings)

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
            "trigger": self.trigger.to_dict() if self.trigger is not None else None,
            "start_step_id": self.start_step_id,
            "terminal_step_ids": list(self.terminal_step_ids),
            "steps": [step.to_dict() for step in self.steps],
            "edges": [edge.to_dict() for edge in self.edges],
            "input_schema": dict(self.input_schema),
            "output_schema": dict(self.output_schema),
            "policies": self.policies.to_dict(),
            "max_step_visits": self.max_step_visits,
            "metadata": dict(self.metadata),
        }


class WorkflowSpecRegistry:
    def __init__(self) -> None:
        self._specs: dict[tuple[str, str], WorkflowSpec] = {}
        self._active_versions: dict[str, str] = {}
        self._deprecated_versions: set[tuple[str, str]] = set()

    def register(self, workflow: WorkflowSpec, *, active: bool = True) -> None:
        workflow.validate()
        key = (workflow.workflow_id, workflow.version)
        if key in self._specs:
            raise WorkflowSpecError(
                f"workflow version is already registered: {workflow.workflow_id}@{workflow.version}"
            )
        self._specs[key] = workflow
        if active:
            self._active_versions[workflow.workflow_id] = workflow.version

    def get(self, workflow_id: str, version: str | None = None) -> WorkflowSpec:
        actual_version = version or self._active_versions.get(workflow_id)
        if actual_version is None:
            raise WorkflowSpecError(f"workflow is not registered: {workflow_id}")
        key = (workflow_id, actual_version)
        try:
            return self._specs[key]
        except KeyError as exc:
            raise WorkflowSpecError(
                f"workflow version is not registered: {workflow_id}@{actual_version}"
            ) from exc

    def latest(self, workflow_id: str) -> WorkflowSpec:
        return self.get(workflow_id)

    def list_versions(self, workflow_id: str) -> list[str]:
        return sorted(version for registered_id, version in self._specs if registered_id == workflow_id)

    def deprecate(self, workflow_id: str, version: str) -> None:
        self.get(workflow_id, version)
        self._deprecated_versions.add((workflow_id, version))

    def is_deprecated(self, workflow_id: str, version: str) -> bool:
        return (workflow_id, version) in self._deprecated_versions


def _coerce_policy(owner: Any, field_name: str, model: type) -> None:
    value = getattr(owner, field_name)
    if not isinstance(value, model):
        object.__setattr__(owner, field_name, model(**value))


_SECRET_FIELD_TOKENS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "client_secret",
    "password",
    "secret",
    "token",
)


def _secret_paths(value: Any, path: str = "$") -> list[str]:
    matches: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            if any(token in key_text.casefold() for token in _SECRET_FIELD_TOKENS):
                matches.append(child_path)
            matches.extend(_secret_paths(item, child_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            matches.extend(_secret_paths(item, f"{path}[{index}]"))
    return matches


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


def _strict_keys_available_before_step(
    *,
    workflow: WorkflowSpec,
    target_step_id: str,
    initial_keys: set[str],
) -> set[str]:
    if target_step_id == workflow.start_step_id:
        return set(initial_keys)
    predecessors = _workflow_predecessors(workflow)
    incoming_step_ids = predecessors.get(target_step_id, set())
    if not incoming_step_ids:
        return set(initial_keys)

    step_by_id = {step.step_id: step for step in workflow.steps}
    available: set[str] | None = None
    for predecessor_step_id in incoming_step_ids:
        predecessor_keys = _strict_keys_after_step(
            workflow=workflow,
            step_id=predecessor_step_id,
            initial_keys=initial_keys,
            visiting=set(),
            step_by_id=step_by_id,
            predecessors=predecessors,
        )
        available = predecessor_keys if available is None else available & predecessor_keys
    return available or set(initial_keys)


def _strict_keys_after_step(
    *,
    workflow: WorkflowSpec,
    step_id: str,
    initial_keys: set[str],
    visiting: set[str],
    step_by_id: dict[str, StepSpec],
    predecessors: dict[str, set[str]],
) -> set[str]:
    if step_id in visiting:
        return set(initial_keys)
    visiting = {*visiting, step_id}
    if step_id == workflow.start_step_id:
        before = set(initial_keys)
    else:
        incoming_step_ids = predecessors.get(step_id, set())
        before: set[str] | None = None
        for predecessor_step_id in incoming_step_ids:
            predecessor_keys = _strict_keys_after_step(
                workflow=workflow,
                step_id=predecessor_step_id,
                initial_keys=initial_keys,
                visiting=visiting,
                step_by_id=step_by_id,
                predecessors=predecessors,
            )
            before = predecessor_keys if before is None else before & predecessor_keys
        before = before or set(initial_keys)
    return before | set(step_by_id[step_id].write_keys)


def _workflow_predecessors(workflow: WorkflowSpec) -> dict[str, set[str]]:
    predecessors = {step.step_id: set() for step in workflow.steps}
    for edge in workflow.edges:
        if edge.target_step_id in predecessors:
            predecessors[edge.target_step_id].add(edge.source_step_id)
    for step in workflow.steps:
        fallback_step_id = step.failure_policy.fallback_step_id
        if fallback_step_id in predecessors:
            predecessors[fallback_step_id].add(step.step_id)
    return predecessors


def _validate_parallel_write_conflicts(
    *,
    workflow: WorkflowSpec,
    add_error: Any,
    strict: bool,
) -> None:
    step_by_id = {step.step_id: step for step in workflow.steps}
    for step in workflow.steps:
        if step.step_type == StepType.PARALLEL_GROUP:
            branches = step.metadata.get("branches")
            if not isinstance(branches, list):
                continue
            conflict_strategy = str(step.metadata.get("conflict_strategy") or "error")
            seen: dict[str, str] = {}
            for index, branch in enumerate(branches):
                if not isinstance(branch, dict):
                    add_error(
                        "parallel_branch_invalid",
                        f"parallel_group branch must be an object in step {step.step_id}",
                        step_id=step.step_id,
                        metadata={"branch_index": index},
                    )
                    continue
                branch_id = str(branch.get("branch_id") or branch.get("implementation") or index)
                for key in [str(item) for item in branch.get("write_keys", [])]:
                    if key in seen and conflict_strategy == "error":
                        add_error(
                            "parallel_write_conflict",
                            f"parallel_group step {step.step_id} has write conflict for key {key}",
                            step_id=step.step_id,
                            metadata={
                                "write_key": key,
                                "first_branch_id": seen[key],
                                "second_branch_id": branch_id,
                            },
                        )
                    if conflict_strategy != "namespace":
                        seen.setdefault(key, branch_id)
        if not strict:
            continue
        outgoing = [
            edge.target_step_id
            for edge in workflow.edges
            if edge.source_step_id == step.step_id
        ]
        if len(outgoing) < 2:
            continue
        fanout_writes: dict[str, str] = {}
        for target_step_id in outgoing:
            target = step_by_id.get(target_step_id)
            if target is None:
                continue
            for key in target.write_keys:
                if key in fanout_writes:
                    add_error(
                        "parallel_fanout_write_conflict",
                        f"fan-out targets from {step.step_id} write the same key: {key}",
                        step_id=step.step_id,
                        metadata={
                            "write_key": key,
                            "first_target_step_id": fanout_writes[key],
                            "second_target_step_id": target_step_id,
                        },
                    )
                fanout_writes.setdefault(key, target_step_id)


def _human_review_has_pause_artifact_strategy(step: StepSpec) -> bool:
    if step.metadata.get("pause_artifact_strategy") or step.metadata.get("pause_artifact"):
        return True
    policy = step.artifact_policy
    return bool(policy is not None and policy.write_step_output)


def _llm_decide_is_governance_edge(edge: EdgeSpec) -> bool:
    text = " ".join(
        str(value)
        for value in (
            edge.edge_id,
            edge.target_step_id,
            edge.description,
            edge.metadata.get("route_hint"),
            edge.metadata.get("decision"),
            edge.metadata.get("purpose"),
        )
    ).casefold()
    governance_tokens = (
        "approval",
        "approve",
        "approved",
        "human_approved",
        "publish",
        "quality_pass",
        "quality.pass",
        "safety",
        "safe_to_publish",
    )
    return any(token in text for token in governance_tokens)
