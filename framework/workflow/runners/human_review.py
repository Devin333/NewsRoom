from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal


HumanReviewDecisionValue = Literal["approved", "rejected", "needs_changes"]

HUMAN_REVIEW_DECISIONS = {"approved", "rejected", "needs_changes"}


@dataclass(frozen=True)
class HumanReviewDecision:
    decision: HumanReviewDecisionValue
    actor_id: str
    reason: str | None = None
    patch: dict[str, Any] | None = None
    decided_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.decision not in HUMAN_REVIEW_DECISIONS:
            raise ValueError(f"invalid human review decision: {self.decision}")
        if not str(self.actor_id or "").strip():
            raise ValueError("human review actor_id is required")
        if self.patch is not None and not isinstance(self.patch, dict):
            raise ValueError("human review patch must be an object or None")
        if not isinstance(self.metadata, dict):
            raise ValueError("human review metadata must be an object")

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "actor_id": self.actor_id,
            "reason": self.reason,
            "patch": dict(self.patch) if self.patch is not None else None,
            "decided_at": self.decided_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> HumanReviewDecision:
        if not isinstance(payload, dict):
            raise ValueError("human review decision must be an object")
        patch = payload.get("patch")
        if patch is not None and not isinstance(patch, dict):
            raise ValueError("human review patch must be an object or None")
        metadata = payload.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise ValueError("human review metadata must be an object")
        return cls(
            decision=str(payload.get("decision") or ""),
            actor_id=str(payload.get("actor_id") or ""),
            reason=_optional_str(payload.get("reason")),
            patch=dict(patch) if patch is not None else None,
            decided_at=_optional_str(payload.get("decided_at")),
            metadata=dict(metadata),
        )


@dataclass(frozen=True)
class HumanReviewRequest:
    request_id: str
    run_id: str
    step_id: str
    workflow_id: str
    workflow_version: str
    checkpoint_id: str | None
    review_type: str
    required_role: str | None
    created_at: str
    expires_at: str | None
    inputs: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.request_id or "").strip():
            raise ValueError("human review request_id is required")
        if not str(self.run_id or "").strip():
            raise ValueError("human review run_id is required")
        if not str(self.step_id or "").strip():
            raise ValueError("human review step_id is required")
        if not str(self.workflow_id or "").strip():
            raise ValueError("human review workflow_id is required")
        if not str(self.workflow_version or "").strip():
            raise ValueError("human review workflow_version is required")
        if not isinstance(self.inputs, dict):
            raise ValueError("human review inputs must be an object")
        if not isinstance(self.metadata, dict):
            raise ValueError("human review metadata must be an object")

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "workflow_id": self.workflow_id,
            "workflow_version": self.workflow_version,
            "checkpoint_id": self.checkpoint_id,
            "review_type": self.review_type,
            "required_role": self.required_role,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "inputs": dict(self.inputs),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> HumanReviewRequest:
        if not isinstance(payload, dict):
            raise ValueError("human review request must be an object")
        return cls(
            request_id=str(payload.get("request_id") or ""),
            run_id=str(payload.get("run_id") or ""),
            step_id=str(payload.get("step_id") or ""),
            workflow_id=str(payload.get("workflow_id") or ""),
            workflow_version=str(payload.get("workflow_version") or ""),
            checkpoint_id=_optional_str(payload.get("checkpoint_id")),
            review_type=str(payload.get("review_type") or "human_review"),
            required_role=_optional_str(payload.get("required_role")),
            created_at=str(payload.get("created_at") or ""),
            expires_at=_optional_str(payload.get("expires_at")),
            inputs=dict(payload.get("inputs") or {}),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class HumanReviewBinding:
    approval_id: str
    request_id: str
    run_id: str
    step_id: str
    checkpoint_id: str

    def __post_init__(self) -> None:
        for field_name in ("approval_id", "request_id", "run_id", "step_id", "checkpoint_id"):
            if not str(getattr(self, field_name) or "").strip():
                raise ValueError(f"human review {field_name} is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "request_id": self.request_id,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "checkpoint_id": self.checkpoint_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> HumanReviewBinding:
        if not isinstance(payload, dict):
            raise ValueError("human review binding must be an object")
        return cls(
            approval_id=str(payload.get("approval_id") or ""),
            request_id=str(payload.get("request_id") or ""),
            run_id=str(payload.get("run_id") or ""),
            step_id=str(payload.get("step_id") or ""),
            checkpoint_id=str(payload.get("checkpoint_id") or ""),
        )


@dataclass(frozen=True)
class HumanReviewActor:
    actor_id: str
    roles: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not str(self.actor_id or "").strip():
            raise ValueError("human review actor_id is required")
        object.__setattr__(self, "roles", [str(role) for role in self.roles])
        object.__setattr__(self, "permissions", [str(permission) for permission in self.permissions])


class HumanReviewPermissionChecker:
    def can_decide(
        self,
        *,
        actor: HumanReviewActor,
        request: HumanReviewRequest,
        decision: HumanReviewDecision,
    ) -> bool:
        _ = decision
        if "admin" in actor.roles or "workflow_admin" in actor.roles:
            return True
        required_role = request.required_role
        if required_role and required_role not in actor.roles:
            return False
        required_permission = request.metadata.get("required_permission")
        if required_permission and str(required_permission) not in actor.permissions:
            return False
        return True


def validate_human_review_binding(
    *,
    checkpoint_run_id: str,
    checkpoint_id: str,
    current_step_ids: list[str],
    request_payload: dict[str, Any] | None,
    decision_payload: dict[str, Any],
    strict: bool = True,
) -> None:
    if not strict:
        return
    if not request_payload:
        raise ValueError("human review request is required for strict resume")
    request = HumanReviewRequest.from_dict(request_payload)
    approval_id = _payload_str(decision_payload, "approval_id")
    request_id = _payload_str(decision_payload, "request_id")
    if not approval_id and not request_id:
        raise ValueError("human review decision requires approval_id or request_id")
    expected_approval_id = _payload_str(request.metadata, "approval_id")
    if approval_id and expected_approval_id and approval_id != expected_approval_id:
        raise ValueError("human review approval_id does not match request")
    if request_id and request_id != request.request_id:
        raise ValueError("human review request_id does not match request")
    if request.run_id != checkpoint_run_id:
        raise ValueError("human review request run_id does not match checkpoint")
    if request.checkpoint_id and request.checkpoint_id != checkpoint_id:
        raise ValueError("human review request checkpoint_id does not match checkpoint")
    if request.step_id not in current_step_ids:
        raise ValueError("human review request step_id is not paused in checkpoint")


def ensure_human_review_not_expired(
    *,
    request_payload: dict[str, Any] | None,
    now: datetime | None = None,
) -> None:
    if not request_payload:
        return
    request = HumanReviewRequest.from_dict(request_payload)
    if request.expires_at is None:
        return
    expires_at = _parse_iso_datetime(request.expires_at)
    actual_now = now or datetime.now(UTC)
    if actual_now.astimezone(UTC) > expires_at:
        raise ValueError("human review request has expired")


def ensure_human_review_permission(
    *,
    request_payload: dict[str, Any] | None,
    decision_payload: dict[str, Any],
) -> None:
    if not request_payload:
        return
    request = HumanReviewRequest.from_dict(request_payload)
    decision = HumanReviewDecision.from_dict(decision_payload)
    metadata = dict(decision_payload.get("metadata") or {})
    actor = HumanReviewActor(
        actor_id=decision.actor_id,
        roles=_string_list(
            decision_payload.get("actor_roles")
            or decision_payload.get("roles")
            or metadata.get("actor_roles")
            or metadata.get("roles")
        ),
        permissions=_string_list(
            decision_payload.get("actor_permissions")
            or decision_payload.get("permissions")
            or metadata.get("actor_permissions")
            or metadata.get("permissions")
        ),
    )
    if not HumanReviewPermissionChecker().can_decide(
        actor=actor,
        request=request,
        decision=decision,
    ):
        raise ValueError("human review actor lacks required role or permission")


def human_review_request_id(
    *,
    run_id: str,
    step_id: str,
    checkpoint_id: str | None = None,
) -> str:
    checkpoint_part = checkpoint_id or "latest"
    return f"human_review:{run_id}:{step_id}:{checkpoint_part}"


def human_review_expires_at(
    *,
    created_at: str,
    timeout_seconds: Any,
) -> str | None:
    if timeout_seconds is None:
        return None
    seconds = float(timeout_seconds)
    if seconds <= 0:
        return None
    created = _parse_iso_datetime(created_at)
    return (created + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _payload_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if value is None:
        return ""
    return str(value)


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]
    return [str(value)]


def _parse_iso_datetime(value: str) -> datetime:
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)



