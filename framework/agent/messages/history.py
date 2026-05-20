from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.agent.messages.message import AgentMessage


@dataclass
class MessageHistory:
    messages: list[AgentMessage] = field(default_factory=list)

    def append(self, message: AgentMessage) -> None:
        self.messages.append(message)

    def extend(self, messages: list[AgentMessage]) -> None:
        self.messages.extend(messages)

    def latest(self, limit: int) -> list[AgentMessage]:
        return list(self.messages[-limit:]) if limit > 0 else []

    def to_llm_messages(self) -> list[dict[str, Any]]:
        return [{"role": message.to_dict()["role"], "content": message.content} for message in self.messages]

    def to_dict(self) -> dict[str, Any]:
        return {"messages": [message.to_dict() for message in self.messages]}
