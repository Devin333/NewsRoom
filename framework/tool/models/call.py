from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from framework.tool.governance.redaction import redact_sensitive_values


@dataclass(frozen=True)
class ToolCall:
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    requested_by_agent_id: str = ""
    call_id: str = field(default_factory=lambda: uuid4().hex)
    requested_by: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        requested_by = self.requested_by
        if requested_by is None and self.requested_by_agent_id:
            requested_by = self.requested_by_agent_id
        requested_by_agent_id = self.requested_by_agent_id or (requested_by or "")
        object.__setattr__(self, "requested_by", requested_by)
        object.__setattr__(self, "requested_by_agent_id", requested_by_agent_id)
        object.__setattr__(self, "arguments", dict(self.arguments or {}))
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    @classmethod
    def new(
        cls,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        requested_by: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "ToolCall":
        return cls(
            tool_name=tool_name,
            arguments=dict(arguments),
            requested_by=requested_by,
            metadata=dict(metadata or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "arguments": redact_sensitive_values(dict(self.arguments)),
            "requested_by": self.requested_by,
            "requested_by_agent_id": self.requested_by_agent_id,
            "metadata": redact_sensitive_values(dict(self.metadata)),
        }
