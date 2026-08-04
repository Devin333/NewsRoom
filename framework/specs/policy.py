"""Declarative workflow policy specification models."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

from framework.specs.validation import WorkflowSpecError

TRACE_POLICY_LEVELS = {"minimal", "standard", "full"}
GATE_POLICY_MODES = {"and", "warn_only"}
GATE_POLICY_DIMENSIONS = {
    "compatibility",
    "safety",
    "resource",
    "correctness",
    "checkpoint",
    "trace",
    "artifact",
}


@dataclass(frozen=True)
class RetryPolicySpec:
    max_retries: int = 0
    retry_delay_seconds: list[int] = field(default_factory=list)
    backoff_strategy: str = "fixed"
    retry_on_error_types: list[str] = field(default_factory=list)
    no_retry_on_error_types: list[str] = field(default_factory=list)
    max_attempts: int | None = None
    backoff_seconds: float | None = None
    backoff_multiplier: float | None = None

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise WorkflowSpecError("max_retries must be non-negative")
        if any(delay < 0 for delay in self.retry_delay_seconds):
            raise WorkflowSpecError("retry_delay_seconds values must be non-negative")
        if not self.backoff_strategy:
            raise WorkflowSpecError("backoff_strategy is required")
        if self.max_attempts is not None and self.max_attempts < 1:
            raise WorkflowSpecError("max_attempts must be at least 1")
        if self.backoff_seconds is not None and self.backoff_seconds < 0:
            raise WorkflowSpecError("backoff_seconds must be non-negative")
        if self.backoff_multiplier is not None and self.backoff_multiplier < 1:
            raise WorkflowSpecError("backoff_multiplier must be at least 1")

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

    def delay_for_attempt(self, attempt: int) -> float:
        if attempt < 1:
            raise WorkflowSpecError("attempt must be at least 1")
        if self.backoff_seconds is not None:
            multiplier = self.backoff_multiplier if self.backoff_multiplier is not None else 1.0
            return self.backoff_seconds * (multiplier ** (attempt - 1))
        return float(self.delay_for_retry(attempt))

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "max_retries": self.max_retries,
            "retry_delay_seconds": list(self.retry_delay_seconds),
            "backoff_strategy": self.backoff_strategy,
            "retry_on_error_types": list(self.retry_on_error_types),
            "no_retry_on_error_types": list(self.no_retry_on_error_types),
        }
        if self.max_attempts is not None:
            payload["max_attempts"] = self.max_attempts
        if self.backoff_seconds is not None:
            payload["backoff_seconds"] = self.backoff_seconds
        if self.backoff_multiplier is not None:
            payload["backoff_multiplier"] = self.backoff_multiplier
        return payload


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
    min_start_window_seconds: float = 0.0
    cancellation_grace_seconds: float | None = None
    completion_reserve_seconds: float = 0.0
    on_timeout: str = "fail"

    def __post_init__(self) -> None:
        if self.timeout_seconds is not None:
            _finite_number(
                "timeout_seconds",
                self.timeout_seconds,
                minimum=0.0,
                strict_minimum=True,
            )
        _finite_number(
            "min_start_window_seconds",
            self.min_start_window_seconds,
            minimum=0.0,
        )
        if self.cancellation_grace_seconds is not None:
            _finite_number(
                "cancellation_grace_seconds",
                self.cancellation_grace_seconds,
                minimum=0.0,
            )
        _finite_number(
            "completion_reserve_seconds",
            self.completion_reserve_seconds,
            minimum=0.0,
        )
        if (
            self.timeout_seconds is not None
            and self.min_start_window_seconds > self.timeout_seconds
        ):
            raise WorkflowSpecError(
                "min_start_window_seconds must not exceed timeout_seconds"
            )
        if self.on_timeout not in {"fail", "retry"}:
            raise WorkflowSpecError("on_timeout must be one of: fail, retry")

    def has_timeout(self) -> bool:
        return self.timeout_seconds is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeout_seconds": self.timeout_seconds,
            "min_start_window_seconds": self.min_start_window_seconds,
            "cancellation_grace_seconds": self.cancellation_grace_seconds,
            "completion_reserve_seconds": self.completion_reserve_seconds,
            "on_timeout": self.on_timeout,
        }


@dataclass(frozen=True)
class ExecutionPolicySpec:
    max_total_retries: int | None = None
    cancellation_grace_seconds: float = 0.1
    verify_reserve_seconds: float = 0.0
    commit_reserve_seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.max_total_retries is not None and (
            type(self.max_total_retries) is not int
            or self.max_total_retries < 0
        ):
            raise WorkflowSpecError(
                "max_total_retries must be a non-negative integer when set"
            )
        for field_name in (
            "cancellation_grace_seconds",
            "verify_reserve_seconds",
            "commit_reserve_seconds",
        ):
            _finite_number(
                field_name,
                getattr(self, field_name),
                minimum=0.0,
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_total_retries": self.max_total_retries,
            "cancellation_grace_seconds": self.cancellation_grace_seconds,
            "verify_reserve_seconds": self.verify_reserve_seconds,
            "commit_reserve_seconds": self.commit_reserve_seconds,
        }


@dataclass(frozen=True)
class ResourcePolicySpec:
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    max_cost_usd: float | None = None
    max_items: int | None = None
    max_parallelism: int | None = None
    max_artifact_bytes: int | None = None
    max_memory_mb: int | None = None
    max_runtime_seconds: float | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "max_input_tokens",
            "max_output_tokens",
            "max_items",
            "max_parallelism",
            "max_artifact_bytes",
            "max_memory_mb",
        ):
            value = getattr(self, field_name)
            if value is not None and value < 0:
                raise WorkflowSpecError(f"{field_name} must be non-negative when set")
        if self.max_cost_usd is not None and self.max_cost_usd < 0:
            raise WorkflowSpecError("max_cost_usd must be non-negative when set")
        if self.max_runtime_seconds is not None and self.max_runtime_seconds < 0:
            raise WorkflowSpecError("max_runtime_seconds must be non-negative when set")

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "max_cost_usd": self.max_cost_usd,
            "max_items": self.max_items,
            "max_parallelism": self.max_parallelism,
            "max_artifact_bytes": self.max_artifact_bytes,
        }
        if self.max_memory_mb is not None:
            payload["max_memory_mb"] = self.max_memory_mb
        if self.max_runtime_seconds is not None:
            payload["max_runtime_seconds"] = self.max_runtime_seconds
        return payload


@dataclass(frozen=True)
class QualityPolicySpec:
    min_citation_coverage: float | None = None
    min_editor_score: float | None = None
    block_on_unsupported_claims: bool = True
    allow_rewrite_count: int = 1
    required: bool = False
    min_score: float | None = None
    evaluator: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("min_citation_coverage", "min_editor_score", "min_score"):
            value = getattr(self, field_name)
            if value is not None and not 0 <= value <= 1:
                raise WorkflowSpecError(f"{field_name} must be between 0 and 1 when set")
        if self.allow_rewrite_count < 0:
            raise WorkflowSpecError("allow_rewrite_count must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "min_citation_coverage": self.min_citation_coverage,
            "min_editor_score": self.min_editor_score,
            "block_on_unsupported_claims": self.block_on_unsupported_claims,
            "allow_rewrite_count": self.allow_rewrite_count,
        }
        if self.required:
            payload["required"] = self.required
        if self.min_score is not None:
            payload["min_score"] = self.min_score
        if self.evaluator is not None:
            payload["evaluator"] = self.evaluator
        return payload


@dataclass(frozen=True)
class ArtifactPolicySpec:
    write_step_input: bool = False
    write_step_output: bool = False
    write_step_error: bool = True
    redacted: bool = True
    artifact_types: list[str] = field(default_factory=list)
    publish_outputs: bool | None = None
    required_artifacts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "write_step_input": self.write_step_input,
            "write_step_output": self.write_step_output,
            "write_step_error": self.write_step_error,
            "redacted": self.redacted,
            "artifact_types": list(self.artifact_types),
        }
        if self.publish_outputs is not None:
            payload["publish_outputs"] = self.publish_outputs
        if self.required_artifacts:
            payload["required_artifacts"] = list(self.required_artifacts)
        return payload


@dataclass(frozen=True)
class LineagePolicySpec:
    enabled: bool = True
    input_keys: list[str] = field(default_factory=list)
    output_keys: list[str] = field(default_factory=list)
    capture_inputs: bool | None = None
    capture_outputs: bool | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "enabled": self.enabled,
            "input_keys": list(self.input_keys),
            "output_keys": list(self.output_keys),
            "metadata": dict(self.metadata),
        }
        if self.capture_inputs is not None:
            payload["capture_inputs"] = self.capture_inputs
        if self.capture_outputs is not None:
            payload["capture_outputs"] = self.capture_outputs
        return payload


@dataclass(frozen=True)
class TracePolicySpec:
    enabled: bool = True
    level: str = "standard"
    include_inputs: bool = False
    include_outputs: bool = True
    include_metrics: bool = True
    include_tool_calls: bool = True
    include_llm_calls: bool = True
    include_memory_ops: bool = True
    redact_secrets: bool = True
    max_payload_bytes: int = 256_000

    def __post_init__(self) -> None:
        object.__setattr__(self, "level", str(self.level))
        object.__setattr__(self, "max_payload_bytes", int(self.max_payload_bytes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "level": self.level,
            "include_inputs": self.include_inputs,
            "include_outputs": self.include_outputs,
            "include_metrics": self.include_metrics,
            "include_tool_calls": self.include_tool_calls,
            "include_llm_calls": self.include_llm_calls,
            "include_memory_ops": self.include_memory_ops,
            "redact_secrets": self.redact_secrets,
            "max_payload_bytes": self.max_payload_bytes,
        }


@dataclass(frozen=True)
class EvaluationPolicySpec:
    enabled: bool = False
    required_output_keys: list[str] = field(default_factory=list)
    required_artifact_kinds: list[str] = field(default_factory=list)
    assertions: list[dict[str, Any]] = field(default_factory=list)
    fail_on_missing_required_output: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "required_output_keys", [str(key) for key in self.required_output_keys])
        object.__setattr__(self, "required_artifact_kinds", [str(kind) for kind in self.required_artifact_kinds])
        object.__setattr__(self, "assertions", [dict(assertion) for assertion in self.assertions])
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "required_output_keys": list(self.required_output_keys),
            "required_artifact_kinds": list(self.required_artifact_kinds),
            "assertions": [dict(assertion) for assertion in self.assertions],
            "fail_on_missing_required_output": self.fail_on_missing_required_output,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class GatePolicySpec:
    enabled: bool = True
    mode: str = "and"
    require_trace: bool = False
    require_manifest: bool = True
    require_checkpoint_for_pause: bool = True
    fail_on_safety_warning: bool = True
    fail_on_policy_violation: bool = True
    dimensions: list[str] = field(
        default_factory=lambda: ["compatibility", "safety", "resource"]
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", str(self.mode))
        object.__setattr__(self, "dimensions", [str(dimension) for dimension in self.dimensions])

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "mode": self.mode,
            "require_trace": self.require_trace,
            "require_manifest": self.require_manifest,
            "require_checkpoint_for_pause": self.require_checkpoint_for_pause,
            "fail_on_safety_warning": self.fail_on_safety_warning,
            "fail_on_policy_violation": self.fail_on_policy_violation,
            "dimensions": list(self.dimensions),
        }


@dataclass(frozen=True)
class RuntimeQualityPolicySpec:
    trace: TracePolicySpec = field(default_factory=TracePolicySpec)
    evaluation: EvaluationPolicySpec = field(default_factory=EvaluationPolicySpec)
    gate: GatePolicySpec = field(default_factory=GatePolicySpec)

    def __post_init__(self) -> None:
        if not isinstance(self.trace, TracePolicySpec):
            object.__setattr__(self, "trace", TracePolicySpec(**self.trace))
        if not isinstance(self.evaluation, EvaluationPolicySpec):
            object.__setattr__(self, "evaluation", EvaluationPolicySpec(**self.evaluation))
        if not isinstance(self.gate, GatePolicySpec):
            object.__setattr__(self, "gate", GatePolicySpec(**self.gate))

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace": self.trace.to_dict(),
            "evaluation": self.evaluation.to_dict(),
            "gate": self.gate.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RuntimeQualityPolicySpec":
        return cls(**payload)


@dataclass(frozen=True, init=False)
class WorkflowPolicySpec:
    execution_policy: ExecutionPolicySpec = field(default_factory=ExecutionPolicySpec)
    retry_policy: RetryPolicySpec = field(default_factory=RetryPolicySpec)
    timeout_policy: TimeoutPolicySpec = field(default_factory=TimeoutPolicySpec)
    failure_policy: FailurePolicySpec = field(default_factory=FailurePolicySpec)
    resource_policy: ResourcePolicySpec = field(default_factory=ResourcePolicySpec)
    quality_policy: QualityPolicySpec | None = None
    artifact_policy: ArtifactPolicySpec | None = None
    lineage_policy: LineagePolicySpec | None = None
    runtime_quality: RuntimeQualityPolicySpec = field(default_factory=RuntimeQualityPolicySpec)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __init__(
        self,
        execution_policy: ExecutionPolicySpec | dict[str, Any] | None = None,
        retry_policy: RetryPolicySpec | dict[str, Any] | None = None,
        timeout_policy: TimeoutPolicySpec | dict[str, Any] | None = None,
        failure_policy: FailurePolicySpec | dict[str, Any] | None = None,
        resource_policy: ResourcePolicySpec | dict[str, Any] | None = None,
        quality_policy: QualityPolicySpec | dict[str, Any] | None = None,
        artifact_policy: ArtifactPolicySpec | dict[str, Any] | None = None,
        lineage_policy: LineagePolicySpec | dict[str, Any] | None = None,
        runtime_quality: RuntimeQualityPolicySpec | dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        *,
        execution: ExecutionPolicySpec | dict[str, Any] | None = None,
        retry: RetryPolicySpec | dict[str, Any] | None = None,
        timeout: TimeoutPolicySpec | dict[str, Any] | None = None,
        failure: FailurePolicySpec | dict[str, Any] | None = None,
        resource: ResourcePolicySpec | dict[str, Any] | None = None,
        quality: QualityPolicySpec | dict[str, Any] | None = None,
        artifact: ArtifactPolicySpec | dict[str, Any] | None = None,
        lineage: LineagePolicySpec | dict[str, Any] | None = None,
    ) -> None:
        object.__setattr__(
            self,
            "execution_policy",
            execution
            if execution is not None
            else execution_policy or ExecutionPolicySpec(),
        )
        object.__setattr__(self, "retry_policy", retry if retry is not None else retry_policy or RetryPolicySpec())
        object.__setattr__(
            self,
            "timeout_policy",
            timeout if timeout is not None else timeout_policy or TimeoutPolicySpec(),
        )
        object.__setattr__(
            self,
            "failure_policy",
            failure if failure is not None else failure_policy or FailurePolicySpec(),
        )
        object.__setattr__(
            self,
            "resource_policy",
            resource if resource is not None else resource_policy or ResourcePolicySpec(),
        )
        object.__setattr__(
            self,
            "quality_policy",
            quality if quality is not None else quality_policy,
        )
        object.__setattr__(
            self,
            "artifact_policy",
            artifact if artifact is not None else artifact_policy,
        )
        object.__setattr__(
            self,
            "lineage_policy",
            lineage if lineage is not None else lineage_policy,
        )
        object.__setattr__(
            self,
            "runtime_quality",
            runtime_quality if runtime_quality is not None else RuntimeQualityPolicySpec(),
        )
        object.__setattr__(self, "metadata", dict(metadata or {}))
        self.__post_init__()

    def __post_init__(self) -> None:
        _coerce_policy(self, "execution_policy", ExecutionPolicySpec)
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
        if not isinstance(self.runtime_quality, RuntimeQualityPolicySpec):
            object.__setattr__(
                self,
                "runtime_quality",
                RuntimeQualityPolicySpec(**self.runtime_quality),
            )

    @property
    def execution(self) -> ExecutionPolicySpec:
        return self.execution_policy

    @property
    def retry(self) -> RetryPolicySpec:
        return self.retry_policy

    @property
    def timeout(self) -> TimeoutPolicySpec:
        return self.timeout_policy

    @property
    def failure(self) -> FailurePolicySpec:
        return self.failure_policy

    @property
    def resource(self) -> ResourcePolicySpec:
        return self.resource_policy

    @property
    def quality(self) -> QualityPolicySpec | None:
        return self.quality_policy

    @property
    def artifact(self) -> ArtifactPolicySpec | None:
        return self.artifact_policy

    @property
    def lineage(self) -> LineagePolicySpec | None:
        return self.lineage_policy

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "execution_policy": self.execution_policy.to_dict(),
            "retry_policy": self.retry_policy.to_dict(),
            "timeout_policy": self.timeout_policy.to_dict(),
            "failure_policy": self.failure_policy.to_dict(),
            "resource_policy": self.resource_policy.to_dict(),
            "quality_policy": (
                self.quality_policy.to_dict() if self.quality_policy is not None else None
            ),
            "metadata": dict(self.metadata),
        }
        if self.artifact_policy is not None:
            payload["artifact_policy"] = self.artifact_policy.to_dict()
        if self.lineage_policy is not None:
            payload["lineage_policy"] = self.lineage_policy.to_dict()
        payload["runtime_quality"] = self.runtime_quality.to_dict()
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WorkflowPolicySpec":
        return cls(**payload)


def _coerce_policy(owner: Any, field_name: str, model: type) -> None:
    value = getattr(owner, field_name)
    if not isinstance(value, model):
        object.__setattr__(owner, field_name, model(**value))


def _finite_number(
    field_name: str,
    value: Any,
    *,
    minimum: float,
    strict_minimum: bool = False,
) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise WorkflowSpecError(f"{field_name} must be a finite number")
    if strict_minimum and float(value) <= minimum:
        raise WorkflowSpecError(f"{field_name} must be greater than {minimum:g}")
    if not strict_minimum and float(value) < minimum:
        raise WorkflowSpecError(f"{field_name} must be at least {minimum:g}")


__all__ = [
    "ArtifactPolicySpec",
    "FailurePolicySpec",
    "LineagePolicySpec",
    "EvaluationPolicySpec",
    "ExecutionPolicySpec",
    "GatePolicySpec",
    "RuntimeQualityPolicySpec",
    "QualityPolicySpec",
    "ResourcePolicySpec",
    "RetryPolicySpec",
    "TimeoutPolicySpec",
    "TracePolicySpec",
    "WorkflowPolicySpec",
]
