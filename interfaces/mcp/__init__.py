"""Inbound MCP-facing interface models."""

from interfaces.mcp.models import (
    MCPCatalog,
    MCPPrompt,
    MCPPromptGetResult,
    MCPResource,
    MCPResourceReadResult,
    MCPTool,
    MCPToolCallResult,
)

__all__ = [
    "MCPCatalog",
    "MCPPrompt",
    "MCPPromptGetResult",
    "MCPResource",
    "MCPResourceReadResult",
    "MCPTool",
    "MCPToolCallResult",
]
