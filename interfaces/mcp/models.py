from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MCPTool:
    name: str
    title: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "input_schema": dict(self.input_schema),
        }


@dataclass(frozen=True)
class MCPResource:
    uri: str
    name: str
    description: str
    mime_type: str = "application/json"

    def to_dict(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "name": self.name,
            "description": self.description,
            "mime_type": self.mime_type,
        }


@dataclass(frozen=True)
class MCPPrompt:
    name: str
    description: str
    arguments_schema: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "arguments_schema": dict(self.arguments_schema),
        }


@dataclass(frozen=True)
class MCPCatalog:
    tools: list[MCPTool]
    resources: list[MCPResource]
    prompts: list[MCPPrompt]

    def to_dict(self) -> dict[str, Any]:
        return {
            "tools": [tool.to_dict() for tool in self.tools],
            "resources": [resource.to_dict() for resource in self.resources],
            "prompts": [prompt.to_dict() for prompt in self.prompts],
        }


@dataclass(frozen=True)
class MCPToolCallResult:
    tool_name: str
    success: bool
    data: dict[str, Any] | None = None
    error_type: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "success": self.success,
            "data": dict(self.data) if self.data is not None else None,
            "error_type": self.error_type,
            "error_message": self.error_message,
        }
