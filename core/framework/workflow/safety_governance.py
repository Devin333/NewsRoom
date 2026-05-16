from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.framework.specs import StepSpec, StepType


@dataclass(frozen=True)
class RuntimeSafetyPolicy:
    require_approval_for_external_write: bool = True
    require_approval_for_publish: bool = True
    require_approval_for_notification: bool = True
    blocked_step_types: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "blocked_step_types",
            [str(step_type) for step_type in self.blocked_step_types],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "require_approval_for_external_write": self.require_approval_for_external_write,
            "require_approval_for_publish": self.require_approval_for_publish,
            "require_approval_for_notification": self.require_approval_for_notification,
            "blocked_step_types": list(self.blocked_step_types),
        }


def safety_violation_for_step(
    step: StepSpec,
    policy: RuntimeSafetyPolicy | None = None,
) -> dict[str, Any] | None:
    effective_policy = policy or RuntimeSafetyPolicy()
    if step.step_type.value in effective_policy.blocked_step_types:
        return _violation(step, code="runtime_safety.blocked_step_type")
    if _step_has_safety_approval(step):
        return None
    if (
        effective_policy.require_approval_for_notification
        and step.step_type == StepType.NOTIFICATION
    ):
        return _violation(step, code="runtime_safety.notification_requires_approval")
    if (
        effective_policy.require_approval_for_publish
        and step.step_type == StepType.ARTIFACT
        and bool(step.metadata.get("publish"))
    ):
        return _violation(step, code="runtime_safety.publish_requires_approval")
    if (
        effective_policy.require_approval_for_external_write
        and _external_write_step(step)
    ):
        return _violation(step, code="runtime_safety.external_write_requires_approval")
    return None


def _step_has_safety_approval(step: StepSpec) -> bool:
    return bool(
        step.metadata.get("safety_approved")
        or step.metadata.get("approval_id")
        or step.metadata.get("approved_by")
    )


def _external_write_step(step: StepSpec) -> bool:
    if step.step_type == StepType.PERSIST and bool(step.metadata.get("external_write")):
        return True
    if step.step_type == StepType.TOOL_CALL and bool(step.metadata.get("dangerous")):
        return True
    if step.step_type == StepType.MEMORY_INDEX and bool(step.metadata.get("external")):
        return True
    return False


def _violation(step: StepSpec, *, code: str) -> dict[str, Any]:
    return {
        "step_id": step.step_id,
        "step_type": step.step_type.value,
        "policy": code,
        "code": code,
        "message": f"step {step.step_id} blocked by runtime safety policy: {code}",
        "metadata": {
            "implementation": step.implementation,
        },
    }
