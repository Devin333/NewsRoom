from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


MCP_CAPABILITY_MANIFEST_SCHEMA_VERSION = "newsroom.mcp_capability_manifest.v1"
INBOUND_MCP_BOUNDARY = "inbound_mcp_server"


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
class MCPCapability:
    name: str
    kind: Literal["tool", "resource", "prompt"]
    title: str
    description: str
    permission: str
    read_only: bool
    category: str = "mcp"
    boundary: Literal["inbound_mcp_server"] = INBOUND_MCP_BOUNDARY
    risk_level: Literal["low", "medium", "high"] = "low"
    requires_approval: bool = False
    uri_template: str | None = None
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_mime_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "title": self.title,
            "description": self.description,
            "permission": self.permission,
            "read_only": self.read_only,
            "category": self.category,
            "boundary": self.boundary,
            "risk_level": self.risk_level,
            "requires_approval": self.requires_approval,
            "uri_template": self.uri_template,
            "input_schema": dict(self.input_schema),
            "output_mime_type": self.output_mime_type,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class MCPCapabilityManifest:
    version: str
    capabilities: list[MCPCapability]
    server_name: str = "NewsRoom"
    transport: str = "stdio/http"
    auth_required: bool = True
    default_permission: str = "mcp:read"
    schema_version: str = MCP_CAPABILITY_MANIFEST_SCHEMA_VERSION
    boundary: Literal["inbound_mcp_server"] = INBOUND_MCP_BOUNDARY

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "version": self.version,
            "server_name": self.server_name,
            "transport": self.transport,
            "auth_required": self.auth_required,
            "default_permission": self.default_permission,
            "boundary": self.boundary,
            "capability_count": len(self.capabilities),
            "capabilities": [capability.to_dict() for capability in self.capabilities],
        }


@dataclass(frozen=True)
class MCPPromptGetResult:
    name: str
    success: bool
    description: str | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)
    error_type: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "success": self.success,
            "description": self.description,
            "messages": [dict(message) for message in self.messages],
            "error_type": self.error_type,
            "error_message": self.error_message,
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


@dataclass(frozen=True)
class MCPResourceReadResult:
    uri: str
    success: bool
    mime_type: str = "application/json"
    data: dict[str, Any] | None = None
    error_type: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "success": self.success,
            "mime_type": self.mime_type,
            "data": dict(self.data) if self.data is not None else None,
            "error_type": self.error_type,
            "error_message": self.error_message,
        }
