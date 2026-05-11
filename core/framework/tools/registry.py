from __future__ import annotations

from dataclasses import dataclass

from core.framework.tools.models import ToolDefinition, ToolDefinitionError, ToolExecutorFn


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

    def export_schema_for_llm(self, allowed_tools: list[str] | None = None) -> list[dict]:
        allowed = set(allowed_tools or [])
        definitions = self.list_tools()
        if allowed_tools is not None:
            definitions = [definition for definition in definitions if definition.name in allowed]
        return [definition.to_dict() for definition in definitions]
