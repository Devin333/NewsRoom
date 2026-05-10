"""Inbound MCP-facing interface models."""

from interfaces.mcp.models import MCPCatalog, MCPPrompt, MCPResource, MCPTool, MCPToolCallResult

__all__ = [
    "MCPCatalog",
    "MCPPrompt",
    "MCPResource",
    "MCPTool",
    "MCPToolCallResult",
]
