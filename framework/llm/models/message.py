from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class LLMMessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True)
class LLMMessage:
    role: LLMMessageRole | str
    content: str
    tool_call_id: str | None = None
    name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", _role_value(self.role))

    @classmethod
    def system(cls, content: str) -> LLMMessage:
        return cls(role=LLMMessageRole.SYSTEM, content=content)

    @classmethod
    def user(cls, content: str) -> LLMMessage:
        return cls(role=LLMMessageRole.USER, content=content)

    @classmethod
    def assistant(cls, content: str) -> LLMMessage:
        return cls(role=LLMMessageRole.ASSISTANT, content=content)

    @classmethod
    def tool(cls, content: str, tool_call_id: str) -> LLMMessage:
        return cls(role=LLMMessageRole.TOOL, content=content, tool_call_id=tool_call_id)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "role": _role_value(self.role),
            "content": self.content,
        }
        if self.tool_call_id is not None:
            payload["tool_call_id"] = self.tool_call_id
        if self.name is not None:
            payload["name"] = self.name
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | LLMMessage) -> LLMMessage:
        if isinstance(payload, LLMMessage):
            return payload
        if not isinstance(payload, dict):
            raise TypeError("LLMMessage payload must be a dict")
        return cls(
            role=str(payload.get("role") or ""),
            content=str(payload.get("content") or ""),
            tool_call_id=(
                str(payload["tool_call_id"]) if payload.get("tool_call_id") is not None else None
            ),
            name=str(payload["name"]) if payload.get("name") is not None else None,
            metadata=dict(payload.get("metadata") or {}),
        )


def _role_value(role: LLMMessageRole | str) -> str:
    if isinstance(role, LLMMessageRole):
        return role.value
    return str(role)

