from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.shared.json import to_jsonable


class MCPApprovalStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    REQUIRED = "required"


@dataclass(frozen=True)
class MCPToolDefinition:
    name: str
    side_effect: bool = False
    requires_approval: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.name).strip():
            raise HarnessValidationError("tool name is required")
        object.__setattr__(self, "name", str(self.name))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "side_effect": self.side_effect,
            "requires_approval": self.requires_approval,
            "metadata": to_jsonable(self.metadata),
        }


@dataclass(frozen=True)
class MCPToolRequest:
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.tool_name).strip():
            raise HarnessValidationError("tool_name is required")
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise HarnessValidationError("timeout_seconds must be greater than zero")
        object.__setattr__(self, "tool_name", str(self.tool_name))
        object.__setattr__(self, "arguments", dict(self.arguments))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "arguments": to_jsonable(self.arguments),
            "timeout_seconds": self.timeout_seconds,
            "metadata": to_jsonable(self.metadata),
        }


@dataclass(frozen=True)
class MCPPolicyDecision:
    allowed: bool
    approval_status: MCPApprovalStatus | str
    reason: str | None = None
    audit_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "approval_status", MCPApprovalStatus(self.approval_status))

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "approval_status": self.approval_status.value,
            "reason": self.reason,
            "audit_ref": self.audit_ref,
        }


def evaluate_mcp_policy(
    definition: MCPToolDefinition,
    request: MCPToolRequest,
    *,
    audit_ref: str | None = None,
) -> MCPPolicyDecision:
    if definition.side_effect:
        return MCPPolicyDecision(
            allowed=False,
            approval_status=(
                MCPApprovalStatus.REQUIRED
                if definition.requires_approval
                else MCPApprovalStatus.NOT_REQUIRED
            ),
            reason="side effect tool requires Harness side-effect authorization",
            audit_ref=audit_ref,
        )
    return MCPPolicyDecision(
        allowed=True,
        approval_status=MCPApprovalStatus.NOT_REQUIRED,
        audit_ref=audit_ref,
    )


__all__ = [
    "MCPApprovalStatus",
    "MCPPolicyDecision",
    "MCPToolDefinition",
    "MCPToolRequest",
    "evaluate_mcp_policy",
]
