from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.shared.json import to_jsonable


@dataclass(frozen=True)
class PolicyDecision:
    policy_id: str
    allowed: bool
    decision: str
    reason: str
    risk_level: str = "low"
    requires_approval: bool = False
    audit_required: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_id", str(self.policy_id))
        object.__setattr__(self, "decision", str(self.decision))
        object.__setattr__(self, "risk_level", str(self.risk_level))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @classmethod
    def allow(
        cls,
        policy_id: str,
        *,
        reason: str = "allowed",
        metadata: dict[str, Any] | None = None,
    ) -> "PolicyDecision":
        return cls(
            policy_id=policy_id,
            allowed=True,
            decision="allow",
            reason=reason,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def block(
        cls,
        policy_id: str,
        *,
        reason: str,
        risk_level: str = "medium",
        metadata: dict[str, Any] | None = None,
    ) -> "PolicyDecision":
        return cls(
            policy_id=policy_id,
            allowed=False,
            decision="block",
            reason=reason,
            risk_level=risk_level,
            audit_required=True,
            metadata=dict(metadata or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "allowed": self.allowed,
            "decision": self.decision,
            "reason": self.reason,
            "risk_level": self.risk_level,
            "requires_approval": self.requires_approval,
            "audit_required": self.audit_required,
            "metadata": to_jsonable(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PolicyDecision":
        return cls(
            policy_id=str(payload["policy_id"]),
            allowed=bool(payload["allowed"]),
            decision=str(payload.get("decision") or "allow"),
            reason=str(payload.get("reason") or ""),
            risk_level=str(payload.get("risk_level") or "low"),
            requires_approval=bool(payload.get("requires_approval", False)),
            audit_required=bool(payload.get("audit_required", False)),
            metadata=dict(payload.get("metadata") or {}),
        )
