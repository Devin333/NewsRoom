from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.shared.json import to_jsonable


@dataclass(frozen=True)
class SubAgentToolPolicy:
    subagent_id: str
    allowed_tools: tuple[str, ...]
    policy_ref: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.subagent_id).strip():
            raise HarnessValidationError("subagent_id is required")
        if not self.allowed_tools:
            raise HarnessValidationError("allowed_tools are required")
        if not str(self.policy_ref).strip():
            raise HarnessValidationError("policy_ref is required")
        object.__setattr__(self, "allowed_tools", tuple(str(tool) for tool in self.allowed_tools))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "subagent_id": self.subagent_id,
            "allowed_tools": list(self.allowed_tools),
            "policy_ref": self.policy_ref,
            "metadata": to_jsonable(self.metadata),
        }


@dataclass(frozen=True)
class SubAgentMemoryPolicy:
    subagent_id: str
    allowed_namespaces: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.subagent_id).strip():
            raise HarnessValidationError("subagent_id is required")
        if not self.allowed_namespaces:
            raise HarnessValidationError("allowed_namespaces are required")
        object.__setattr__(self, "allowed_namespaces", tuple(str(namespace) for namespace in self.allowed_namespaces))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "subagent_id": self.subagent_id,
            "allowed_namespaces": list(self.allowed_namespaces),
            "metadata": to_jsonable(self.metadata),
        }


@dataclass(frozen=True)
class SubAgentBudget:
    max_turns: int
    max_tool_calls: int
    max_memory_ops: int

    def __post_init__(self) -> None:
        for field_name in ("max_turns", "max_tool_calls", "max_memory_ops"):
            value = getattr(self, field_name)
            if not isinstance(value, int) or value < 0:
                raise HarnessValidationError(f"{field_name} must be a non-negative integer")

    def to_dict(self) -> dict[str, int]:
        return {
            "max_turns": self.max_turns,
            "max_tool_calls": self.max_tool_calls,
            "max_memory_ops": self.max_memory_ops,
        }


__all__ = ["SubAgentBudget", "SubAgentMemoryPolicy", "SubAgentToolPolicy"]
