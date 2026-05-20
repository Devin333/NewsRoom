from __future__ import annotations

import json
from typing import Any

from framework.agent.messages.history import MessageHistory
from framework.agent.models.action import AgentAction


class AgentMessageFormatter:
    def format_history(self, history: MessageHistory) -> str:
        return "\n".join(json.dumps(message.to_dict(), ensure_ascii=False, sort_keys=True) for message in history.messages)

    def format_action(self, action: AgentAction) -> str:
        return json.dumps(action.to_dict(), ensure_ascii=False, sort_keys=True)

    def format_observation(self, observation: dict[str, Any]) -> str:
        return json.dumps(observation, ensure_ascii=False, sort_keys=True)
