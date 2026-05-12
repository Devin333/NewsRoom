from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from core.framework.tools.models import ToolCall
from core.framework.workers.approval import ApprovalRequest


_VALID_RISK_LEVELS = {"low", "medium", "high", "critical"}


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
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.risk_level not in _VALID_RISK_LEVELS:
            raise ValueError(f"invalid tool approval risk level: {self.risk_level}")
        object.__setattr__(self, "created_at", _normalize_datetime(self.created_at))
        object.__setattr__(self, "metadata", dict(self.metadata))
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
            "step_id": self.step_id,
            "agent_id": self.agent_id,
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "metadata": dict(self.metadata),
        }

    def to_worker_approval_request(self) -> ApprovalRequest:
        return ApprovalRequest(
            approval_id=self.approval_id,
            requested_action=f"tool:{self.tool_name}",
            risk_level=self.risk_level,
            reason=self.reason,
            payload={"tool_approval": self.to_dict()},
            task_id=self.tool_call.call_id,
            run_id=self.run_id,
            requested_by=self.agent_id,
            created_at=self.created_at,
            metadata={
                "approval_type": "tool_execution",
                "tool_name": self.tool_name,
                "side_effect": self.side_effect,
                **self.metadata,
            },
        )


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
