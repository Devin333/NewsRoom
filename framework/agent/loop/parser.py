from __future__ import annotations

import json

from framework.agent.models import AgentAction


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
        return self.parse_json_action(payload)

    def parse_json_action(self, payload: dict[str, object]) -> AgentAction:
        action_type = payload.get("action_type")
        if action_type is None:
            return AgentAction(action_type="final_output", output=payload)
        if action_type not in {
            "tool_call",
            "final",
            "final_output",
            "delegate",
            "delegate_to_subagent",
            "ask_clarification",
            "think",
        }:
            raise AgentActionParserError(f"unsupported agent action type: {action_type}")

        if action_type == "tool_call":
            tool_name = payload.get("tool_name")
            if not isinstance(tool_name, str) or not tool_name:
                raise AgentActionParserError("tool_call action requires tool_name")
            tool_args = payload.get("tool_args", {})
            if not isinstance(tool_args, dict):
                raise AgentActionParserError("tool_args must be an object")
            return AgentAction(action_type="tool_call", tool_name=tool_name, tool_args=tool_args)

        if action_type in {"delegate", "delegate_to_subagent"}:
            subagent_id = payload.get("subagent_id") or payload.get("agent_id")
            if not isinstance(subagent_id, str) or not subagent_id.strip():
                raise AgentActionParserError("delegate_to_subagent action requires subagent_id")
            subagent_task = payload.get("subagent_task") or payload.get("task")
            if subagent_task is not None and not isinstance(subagent_task, str):
                raise AgentActionParserError("subagent_task must be a string")
            handoff_reason = payload.get("handoff_reason")
            if handoff_reason is not None and not isinstance(handoff_reason, str):
                raise AgentActionParserError("handoff_reason must be a string")
            return AgentAction(
                action_type=str(action_type),
                subagent_id=subagent_id,
                subagent_task=subagent_task,
                handoff_reason=handoff_reason,
            )

        if action_type in {"ask_clarification", "think"}:
            content = payload.get("content")
            return AgentAction(
                action_type=str(action_type),
                content=str(content) if content is not None else None,
                metadata={key: value for key, value in payload.items() if key not in {"action_type", "content"}},
            )

        output = payload.get("output")
        if action_type == "final" and output is None and "content" in payload:
            return AgentAction(
                action_type="final",
                content=str(payload.get("content") or ""),
                output={"content": payload.get("content")},
            )
        if not isinstance(output, dict):
            raise AgentActionParserError("final_output action requires object output")
        return AgentAction(action_type=str(action_type), output=output)
