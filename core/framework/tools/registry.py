from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from core.framework.tools.models import (
    ToolDefinition,
    ToolDefinitionError,
    ToolExecutorFn,
    ToolPolicy,
)


DuplicateToolPolicy = Literal["error", "skip", "replace_explicit"]
_DUPLICATE_POLICIES = {"error", "skip", "replace_explicit"}


@dataclass(frozen=True)
class RegisteredTool:
    definition: ToolDefinition
    executor: ToolExecutorFn


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(
        self,
        definition: ToolDefinition,
        executor: ToolExecutorFn,
        *,
        duplicate_policy: DuplicateToolPolicy = "error",
    ) -> RegisteredTool:
        if duplicate_policy not in _DUPLICATE_POLICIES:
            raise ToolDefinitionError(f"unsupported duplicate policy: {duplicate_policy}")

        existing = self._tools.get(definition.name)
        if existing is not None and duplicate_policy == "error":
            raise ToolDefinitionError(f"tool already registered: {definition.name}")
        if existing is not None and duplicate_policy == "skip":
            return existing

        registered = RegisteredTool(definition=definition, executor=executor)
        self._tools[definition.name] = registered
        return registered

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
