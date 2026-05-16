from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from core.framework.specs import StepSpec
from core.framework.workflow.buffer import DataBuffer


@dataclass(frozen=True)
class ResourceUsageEstimate:
    input_items: int
    input_tokens: int
    input_bytes: int
    output_tokens: int = 0
    artifact_bytes: int = 0
    parallelism: int = 0
    input_keys: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_items": self.input_items,
            "input_tokens": self.input_tokens,
            "input_bytes": self.input_bytes,
            "output_tokens": self.output_tokens,
            "artifact_bytes": self.artifact_bytes,
            "parallelism": self.parallelism,
            "input_keys": list(self.input_keys),
        }


@dataclass(frozen=True)
class ResourcePolicyViolation:
    code: str
    message: str
    step_id: str
    limit: int | float
    actual: int | float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "step_id": self.step_id,
            "limit": self.limit,
            "actual": self.actual,
            "metadata": dict(self.metadata),
        }


class StepResourceEstimator:
    def estimate_inputs(self, step: StepSpec, buffer: DataBuffer) -> ResourceUsageEstimate:
        input_items = 0
        input_tokens = 0
        input_bytes = 0
        input_keys: list[str] = []

        for key in step.read_keys:
            if not buffer.exists(key):
                continue
            value = buffer.read(key)
            input_keys.append(str(key))
            input_items += _estimate_items(value)
            input_tokens += _estimate_tokens(value)
            input_bytes += _estimate_bytes(value)

        return ResourceUsageEstimate(
            input_items=input_items,
            input_tokens=input_tokens,
            input_bytes=input_bytes,
            parallelism=_estimate_parallelism(step),
            input_keys=input_keys,
        )


class StepResourceGuard:
    def check(
        self,
        step: StepSpec,
        estimate: ResourceUsageEstimate,
    ) -> list[ResourcePolicyViolation]:
        policy = step.resource_policy
        violations: list[ResourcePolicyViolation] = []
        _append_limit_violation(
            violations,
            step=step,
            code="resource.max_items",
            label="input items",
            limit=policy.max_items,
            actual=estimate.input_items,
            metadata=estimate.to_dict(),
        )
        _append_limit_violation(
            violations,
            step=step,
            code="resource.max_input_tokens",
            label="input tokens",
            limit=policy.max_input_tokens,
            actual=estimate.input_tokens,
            metadata=estimate.to_dict(),
        )
        _append_limit_violation(
            violations,
            step=step,
            code="resource.max_artifact_bytes",
            label="artifact bytes",
            limit=policy.max_artifact_bytes,
            actual=estimate.artifact_bytes,
            metadata=estimate.to_dict(),
        )
        _append_limit_violation(
            violations,
            step=step,
            code="resource.max_parallelism",
            label="parallelism",
            limit=policy.max_parallelism,
            actual=estimate.parallelism,
            metadata=estimate.to_dict(),
        )
        return violations


def _append_limit_violation(
    violations: list[ResourcePolicyViolation],
    *,
    step: StepSpec,
    code: str,
    label: str,
    limit: int | float | None,
    actual: int | float,
    metadata: dict[str, Any],
) -> None:
    if limit is None or actual <= limit:
        return
    violations.append(
        ResourcePolicyViolation(
            code=code,
            message=(
                f"step {step.step_id} estimated {label} {actual}, "
                f"exceeding limit {limit}"
            ),
            step_id=step.step_id,
            limit=limit,
            actual=actual,
            metadata=metadata,
        )
    )


def _estimate_items(value: Any) -> int:
    if isinstance(value, dict) and isinstance(value.get("items"), list):
        return len(value["items"])
    if isinstance(value, (list, tuple, set, dict)):
        return len(value)
    return 0


def _estimate_tokens(value: Any) -> int:
    if isinstance(value, str):
        return max(1, (len(value) + 3) // 4)
    if isinstance(value, bytes):
        return max(1, (len(value) + 3) // 4)
    if isinstance(value, (list, tuple, set)):
        return sum(_estimate_tokens(item) for item in value)
    if isinstance(value, dict):
        return sum(_estimate_tokens(item) for item in value.values())
    return 0


def _estimate_bytes(value: Any) -> int:
    if isinstance(value, bytes):
        return len(value)
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    try:
        return len(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"))
    except TypeError:
        return len(str(value).encode("utf-8"))


def _estimate_parallelism(step: StepSpec) -> int:
    branches = step.metadata.get("branches")
    if isinstance(branches, list):
        return len(branches)
    parallelism = step.metadata.get("parallelism")
    if parallelism is None:
        return 0
    try:
        return max(0, int(parallelism))
    except (TypeError, ValueError):
        return 0
