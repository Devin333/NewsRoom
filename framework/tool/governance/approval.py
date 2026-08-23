from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from enum import Enum
from typing import Any, Protocol
from uuid import uuid4

from framework.shared.time import ensure_utc, format_datetime
from framework.shared.graph_identity import GraphExecutionIdentity
from framework.tool.models.call import ToolCall


_VALID_RISK_LEVELS = {"low", "medium", "high", "critical"}


class ToolApprovalDecision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    MODIFY = "modify"


class ToolApprovalStore(Protocol):
    def upsert_approval(self, request: Any) -> Any: ...


@dataclass(frozen=True)
class ToolApprovalRequest:
    tool_call: ToolCall
    tool_name: str
    side_effect: str
    reason: str
    risk_level: str
    approval_id: str = field(default_factory=lambda: f"tool_appr_{uuid4().hex}")
    run_id: str | None = None
    step_id: str | None = None
    agent_id: str | None = None
    graph_identity: GraphExecutionIdentity | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.risk_level not in _VALID_RISK_LEVELS:
            raise ValueError(f"invalid tool approval risk level: {self.risk_level}")
        if self.step_id is not None:
            raise ValueError("active tool approval cannot carry retired step_id authority")
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))
        object.__setattr__(self, "metadata", dict(self.metadata))
        identity = self.graph_identity
        if identity is not None and not isinstance(identity, GraphExecutionIdentity):
            identity = GraphExecutionIdentity.from_dict(identity)
        if identity is not None and self.run_id is not None and identity.run_id != self.run_id:
            raise ValueError("approval run_id must match graph_identity.run_id")
        object.__setattr__(self, "graph_identity", identity)
        if self.agent_id is None and self.tool_call.requested_by_agent_id:
            object.__setattr__(self, "agent_id", self.tool_call.requested_by_agent_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "tool_name": self.tool_name,
            "tool_call": self.tool_call.to_dict(),
            "side_effect": self.side_effect,
            "reason": self.reason,
            "risk_level": self.risk_level,
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "graph_identity": (
                self.graph_identity.to_dict()
                if self.graph_identity is not None
                else None
            ),
            "created_at": format_datetime(self.created_at),
            "metadata": dict(self.metadata),
        }

    def to_worker_approval_request(self) -> "ApprovalRequest":
        return ApprovalRequest(
            approval_id=self.approval_id,
            requested_action=f"tool:{self.tool_name}",
            risk_level=self.risk_level,
            reason=self.reason,
            payload={"tool_approval": self.to_dict()},
            task_id=self.tool_call.call_id,
            run_id=self.run_id,
            graph_identity=self.graph_identity,
            requested_by=self.agent_id,
            created_at=self.created_at,
            metadata={
                "approval_type": "tool_execution",
                "tool_name": self.tool_name,
                "side_effect": self.side_effect,
                **self.metadata,
            },
        )


@dataclass(frozen=True)
class ApprovalRequest:
    requested_action: str
    risk_level: str = "medium"
    reason: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    approval_id: str = field(default_factory=lambda: f"appr_{uuid4().hex}")
    status: str = "pending"
    task_id: str | None = None
    run_id: str | None = None
    requested_by: str | None = None
    graph_identity: GraphExecutionIdentity | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    decision: Any | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        identity = self.graph_identity
        if identity is not None and not isinstance(identity, GraphExecutionIdentity):
            identity = GraphExecutionIdentity.from_dict(identity)
        if identity is not None:
            if self.run_id is not None and str(self.run_id).strip() != identity.run_id:
                raise ValueError("approval run_id must match graph_identity.run_id")
            object.__setattr__(self, "run_id", identity.run_id)
        object.__setattr__(self, "graph_identity", identity)
        object.__setattr__(self, "payload", dict(self.payload))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def is_pending(self) -> bool:
        return str(self.status) == "pending"

    def with_decision(self, decision: Any) -> "ApprovalRequest":
        decision_type = getattr(decision, "decision_type", decision)
        value = getattr(decision_type, "value", decision_type)
        status = {
            "approve": "approved",
            "reject": "rejected",
            "modify": "modified",
        }.get(str(value), str(value))
        return ApprovalRequest(
            approval_id=self.approval_id,
            requested_action=self.requested_action,
            risk_level=self.risk_level,
            reason=self.reason,
            payload=dict(self.payload),
            status=status,
            task_id=self.task_id,
            run_id=self.run_id,
            graph_identity=self.graph_identity,
            requested_by=self.requested_by,
            created_at=self.created_at,
            expires_at=self.expires_at,
            decision=decision,
            metadata=dict(self.metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        decision_value = self.decision
        decision = (
            decision_value.to_dict()
            if decision_value is not None and hasattr(decision_value, "to_dict")
            else decision_value
        )
        status = getattr(self.status, "value", self.status)
        return {
            "approval_id": self.approval_id,
            "requested_action": self.requested_action,
            "risk_level": self.risk_level,
            "reason": self.reason,
            "payload": dict(self.payload),
            "status": status,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "requested_by": self.requested_by,
            "graph_identity": (
                self.graph_identity.to_dict()
                if self.graph_identity is not None
                else None
            ),
            "created_at": format_datetime(self.created_at),
            "expires_at": format_datetime(self.expires_at),
            "decision": decision,
            "metadata": dict(self.metadata),
        }
