from __future__ import annotations

from typing import Any

from framework.tool import ToolResult
from framework.agent.subagents import SubAgentResult
from framework.agent.runtime.redaction import redact_sensitive_values


class ObservationBuilder:
    def from_tool_result(self, tool_name: str, result: ToolResult) -> dict[str, Any]:
        payload = result.to_dict() if hasattr(result, "to_dict") else {"output": result}
        return {
            "kind": "tool",
            "tool_name": tool_name,
            "status": payload.get("status"),
            "summary": payload.get("output_summary") or payload.get("error_message"),
            "result": redact_sensitive_values(payload),
        }

    def from_subagent_result(self, result: SubAgentResult) -> dict[str, Any]:
        payload = result.to_dict() if hasattr(result, "to_dict") else {"output": result}
        return {
            "kind": "subagent",
            "child_agent_id": payload.get("child_agent_id"),
            "status": payload.get("status"),
            "summary": payload.get("summary") or payload.get("error"),
            "result": redact_sensitive_values(payload),
        }

    def summarize(self, observation: dict[str, Any]) -> str:
        summary = observation.get("summary")
        if summary:
            return str(summary)
        kind = observation.get("kind") or "observation"
        status = observation.get("status") or "unknown"
        return f"{kind} {status}"
