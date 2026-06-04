from __future__ import annotations

from typing import Protocol, runtime_checkable

from framework.harness.mcp.policy import MCPToolDefinition, MCPToolRequest
from framework.harness.workers.result import HarnessWorkerResult


@runtime_checkable
class MCPToolPort(Protocol):
    def list_tools(self) -> tuple[MCPToolDefinition, ...]:
        ...

    def call_tool(self, request: MCPToolRequest) -> HarnessWorkerResult:
        ...


__all__ = ["MCPToolPort"]
