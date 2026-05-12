from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.framework.tools.models import (
    ToolDefinition,
    ToolDefinitionError,
    ToolExecutorFn,
    ToolPolicy,
)


@dataclass(frozen=True)
class RegisteredTool:
    definition: ToolDefinition
    executor: ToolExecutorFn


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, definition: ToolDefinition, executor: ToolExecutorFn) -> None:
        if definition.name in self._tools:
            raise ToolDefinitionError(f"tool already registered: {definition.name}")
        self._tools[definition.name] = RegisteredTool(definition=definition, executor=executor)

    def unregister(self, tool_name: str) -> None:
        self._tools.pop(tool_name, None)

    def get(self, tool_name: str) -> RegisteredTool:
        try:
            return self._tools[tool_name]
        except KeyError as exc:
            raise ToolDefinitionError(f"tool is not registered: {tool_name}") from exc

    def list_tools(self) -> list[ToolDefinition]:
        return [registered.definition for registered in self._tools.values()]

    def list_tools_for_agent(self, agent_id: str, policy: ToolPolicy) -> list[ToolDefinition]:
        _ = agent_id
        return [definition for definition in self.list_tools() if policy.exposes(definition)]

    def export_schema_for_llm(
        self,
        agent_id: str | list[str] = "",
        policy: ToolPolicy | None = None,
    ) -> list[dict[str, Any]]:
        if isinstance(agent_id, list):
            policy = ToolPolicy(allowed_tools=list(agent_id), require_explicit_allowlist=True)
            agent_id = ""

        definitions = self.list_tools()
        if policy is not None:
            definitions = self.list_tools_for_agent(agent_id, policy)
        return [definition.to_dict() for definition in definitions]
