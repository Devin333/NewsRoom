from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from core.framework.tools.models import ToolDefinition
from core.framework.tools.registry import ToolRegistry


@dataclass(frozen=True)
class MCPServerConfig:
    server_id: str
    name: str
    transport: str
    command: str | None = None
    args: list[str] = field(default_factory=list)
    url: str | None = None
    headers_env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    timeout_seconds: float = 30.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.server_id:
            raise ValueError("server_id is required")
        if not self.name:
            raise ValueError("name is required")
        if self.transport not in {"stdio", "http", "sse", "in_memory"}:
            raise ValueError(f"unsupported MCP transport: {self.transport}")


class MCPClientProtocol(Protocol):
    def list_tools(self, server: MCPServerConfig) -> list[dict[str, Any]]: ...

    def call_tool(
        self,
        server: MCPServerConfig,
        remote_tool_name: str,
        arguments: dict[str, Any],
    ) -> Any: ...


class MCPToolAdapter:
    def __init__(self, client: MCPClientProtocol) -> None:
        self._client = client

    def list_tools(self, server: MCPServerConfig) -> list[ToolDefinition]:
        if not server.enabled:
            return []
        return [
            self._definition_from_remote_tool(server, remote_tool)
            for remote_tool in self._client.list_tools(server)
        ]

    def register_tools(self, registry: ToolRegistry, server: MCPServerConfig) -> list[ToolDefinition]:
        definitions = self.list_tools(server)
        for definition in definitions:
            remote_tool_name = str(definition.metadata["remote_tool_name"])
            registry.register(
                definition,
                lambda args, remote_tool_name=remote_tool_name: self._client.call_tool(
                    server,
                    remote_tool_name,
                    args,
                ),
            )
        return definitions

    def _definition_from_remote_tool(
        self,
        server: MCPServerConfig,
        remote_tool: dict[str, Any],
    ) -> ToolDefinition:
        remote_tool_name = str(remote_tool.get("name") or "")
        if not remote_tool_name:
            raise ValueError("remote MCP tool name is required")
        input_schema = remote_tool.get("input_schema") or remote_tool.get("inputSchema") or {}
        if not isinstance(input_schema, dict):
            raise ValueError(f"input schema must be an object for MCP tool {remote_tool_name}")
        return ToolDefinition(
            name=f"mcp.{_safe_name(server.server_id)}.{_safe_name(remote_tool_name)}",
            description=str(remote_tool.get("description") or ""),
            input_schema=dict(input_schema),
            side_effect=str(remote_tool.get("side_effect") or "read_only"),
            is_dangerous=bool(remote_tool.get("is_dangerous", False)),
            requires_approval=bool(remote_tool.get("requires_approval", False)),
            timeout_seconds=server.timeout_seconds,
            concurrency_safe=bool(remote_tool.get("concurrency_safe", False)),
            metadata={
                "source": "mcp",
                "server_id": server.server_id,
                "server_name": server.name,
                "remote_tool_name": remote_tool_name,
                **dict(remote_tool.get("metadata") or {}),
            },
        )


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip())
    return safe.strip("_") or "unnamed"
