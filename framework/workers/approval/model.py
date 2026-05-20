from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from framework.shared.time import ensure_utc, format_datetime, parse_datetime


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ApprovalDecisionType(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    MODIFY = "modify"


class ApprovalNotFoundError(KeyError):
    """Raised when an approval id is not present in a store."""


class ApprovalAlreadyDecidedError(ValueError):
    """Raised when a non-pending approval receives a decision."""


@dataclass(frozen=True)
class ApprovalDecision:
    decision_type: ApprovalDecisionType | str
    decided_by: str
    reason: str | None = None
    modifications: dict[str, Any] = field(default_factory=dict)
    decided_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        object.__setattr__(self, "decision_type", ApprovalDecisionType(self.decision_type))
        object.__setattr__(self, "modifications", dict(self.modifications))
        object.__setattr__(self, "decided_at", ensure_utc(self.decided_at))
        if not self.decided_by:
            raise ValueError("decided_by is required")
        if self.decision_type == ApprovalDecisionType.MODIFY and not self.modifications:
            raise ValueError("modifications are required for modify decisions")
        _reject_secret_payload_keys(self.modifications)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_type": ApprovalDecisionType(self.decision_type).value,
            "decided_by": self.decided_by,
            "reason": self.reason,
            "modifications": dict(self.modifications),
            "decided_at": format_datetime(self.decided_at),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ApprovalDecision":
        return cls(
            decision_type=str(data["decision_type"]),
            decided_by=str(data["decided_by"]),
            reason=data.get("reason"),
            modifications=dict(data.get("modifications") or {}),
            decided_at=parse_datetime(data.get("decided_at")) or datetime.now(UTC),
        )


@dataclass(frozen=True)
class ApprovalRequest:
    requested_action: str
    risk_level: str = "medium"
    reason: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    approval_id: str = field(default_factory=lambda: f"appr_{uuid4().hex}")
    status: ApprovalStatus | str = ApprovalStatus.PENDING
    task_id: str | None = None
    run_id: str | None = None
    requested_by: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    decision: ApprovalDecision | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", ApprovalStatus(self.status))
        object.__setattr__(self, "payload", dict(self.payload))
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))
        object.__setattr__(self, "expires_at", ensure_utc(self.expires_at) if self.expires_at else None)
        if not self.approval_id:
            raise ValueError("approval_id is required")
        if not self.requested_action:
            raise ValueError("requested_action is required")
        if self.decision is not None and not isinstance(self.decision, ApprovalDecision):
            object.__setattr__(self, "decision", ApprovalDecision.from_dict(dict(self.decision)))
        _reject_secret_payload_keys(self.payload)
        _reject_secret_payload_keys(self.metadata)

    @property
    def is_pending(self) -> bool:
        return self.status == ApprovalStatus.PENDING

    def with_decision(self, decision: ApprovalDecision) -> "ApprovalRequest":
        if not self.is_pending:
            raise ApprovalAlreadyDecidedError(f"approval is not pending: {self.approval_id}")
        status_by_decision = {
            ApprovalDecisionType.APPROVE: ApprovalStatus.APPROVED,
            ApprovalDecisionType.REJECT: ApprovalStatus.REJECTED,
            ApprovalDecisionType.MODIFY: ApprovalStatus.MODIFIED,
        }
        return ApprovalRequest(
            approval_id=self.approval_id,
            requested_action=self.requested_action,
            risk_level=self.risk_level,
            reason=self.reason,
            payload=self.payload,
            status=status_by_decision[ApprovalDecisionType(decision.decision_type)],
            task_id=self.task_id,
            run_id=self.run_id,
            requested_by=self.requested_by,
            created_at=self.created_at,
            expires_at=self.expires_at,
            decision=decision,
            metadata=self.metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "requested_action": self.requested_action,
            "risk_level": self.risk_level,
            "reason": self.reason,
            "payload": dict(self.payload),
            "status": ApprovalStatus(self.status).value,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "requested_by": self.requested_by,
            "created_at": format_datetime(self.created_at),
            "expires_at": format_datetime(self.expires_at),
            "decision": self.decision.to_dict() if self.decision else None,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ApprovalRequest":
        decision_payload = data.get("decision")
        return cls(
            approval_id=str(data.get("approval_id") or f"appr_{uuid4().hex}"),
            requested_action=str(data["requested_action"]),
            risk_level=str(data.get("risk_level") or "medium"),
            reason=data.get("reason"),
            payload=dict(data.get("payload") or {}),
            status=str(data.get("status") or ApprovalStatus.PENDING.value),
            task_id=data.get("task_id"),
            run_id=data.get("run_id"),
            requested_by=data.get("requested_by"),
            created_at=parse_datetime(data.get("created_at")) or datetime.now(UTC),
            expires_at=parse_datetime(data.get("expires_at")),
            decision=ApprovalDecision.from_dict(decision_payload) if decision_payload else None,
            metadata=dict(data.get("metadata") or {}),
        )


def _reject_secret_payload_keys(payload: dict[str, Any]) -> None:
    secret_fragments = (
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "password",
        "secret",
        "token",
    )
    for key in payload:
        normalized = str(key).lower().replace("-", "_")
        if any(fragment in normalized for fragment in secret_fragments):
            raise ValueError(f"approval payload key is not allowed: {key}")
