from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any



class AgentActionType(str, Enum):
    FINAL = "final"
    TOOL_CALL = "tool_call"
    ASK_CLARIFICATION = "ask_clarification"
    DELEGATE = "delegate"
    THINK = "think"


@dataclass(frozen=True)
class AgentAction:
    action_type: AgentActionType | str
    content: str | None = None
    output: dict[str, Any] | None = None
    tool_name: str | None = None
    tool_args: dict[str, Any] = field(default_factory=dict)
    subagent_id: str | None = None
    subagent_task: str | None = None
    handoff_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_final(self) -> bool:
        return _action_type_value(self.action_type) in {"final", "final_output"}

    def is_tool_call(self) -> bool:
        return _action_type_value(self.action_type) == "tool_call"

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_type": _action_type_value(self.action_type),
            "content": self.content,
            "output": self.output,
            "tool_name": self.tool_name,
            "tool_args": dict(self.tool_args),
            "subagent_id": self.subagent_id,
            "subagent_task": self.subagent_task,
            "handoff_reason": self.handoff_reason,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def final(cls, content: str) -> "AgentAction":
        return cls(action_type=AgentActionType.FINAL, content=content, output={"content": content})

    @classmethod
    def tool_call(cls, tool_name: str, tool_args: dict[str, Any]) -> "AgentAction":
        return cls(action_type=AgentActionType.TOOL_CALL, tool_name=tool_name, tool_args=dict(tool_args))


def _action_type_value(action_type: AgentActionType | str) -> str:
    return action_type.value if isinstance(action_type, AgentActionType) else str(action_type)
