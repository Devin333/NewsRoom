from __future__ import annotations

import json

from core.framework.agent_loop.models import AgentAction


class AgentActionParserError(ValueError):
    """Raised when an LLM response cannot be parsed as an AgentAction."""


class AgentActionParser:
    def parse(self, content: str) -> AgentAction:
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise AgentActionParserError(f"LLM response is not valid JSON: {exc.msg}") from exc

        if not isinstance(payload, dict):
            raise AgentActionParserError("LLM response must be a JSON object")

        action_type = payload.get("action_type")
        if action_type not in {"tool_call", "final_output"}:
            raise AgentActionParserError(f"unsupported agent action type: {action_type}")

        if action_type == "tool_call":
            tool_name = payload.get("tool_name")
            if not isinstance(tool_name, str) or not tool_name:
                raise AgentActionParserError("tool_call action requires tool_name")
            tool_args = payload.get("tool_args", {})
            if not isinstance(tool_args, dict):
                raise AgentActionParserError("tool_args must be an object")
            return AgentAction(action_type="tool_call", tool_name=tool_name, tool_args=tool_args)

        output = payload.get("output")
        if not isinstance(output, dict):
            raise AgentActionParserError("final_output action requires object output")
        return AgentAction(action_type="final_output", output=output)
