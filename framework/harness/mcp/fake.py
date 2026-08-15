from __future__ import annotations

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.mcp.policy import MCPToolDefinition, MCPToolRequest, evaluate_mcp_policy
from framework.harness.workers.result import HarnessWorkerResult


class FakeMCPToolPort:
    def __init__(self, tools: tuple[MCPToolDefinition, ...] | None = None) -> None:
        self.tools = tools or (
            MCPToolDefinition(name="search.read", side_effect=False, requires_approval=False),
            MCPToolDefinition(name="artifact.write", side_effect=True, requires_approval=True),
        )
        self.audit_events: list[dict] = []

    def list_tools(self) -> tuple[MCPToolDefinition, ...]:
        return self.tools

    def call_tool(self, request: MCPToolRequest) -> HarnessWorkerResult:
        definition = self._definition(request.tool_name)
        audit_ref = f"audit://mcp/{len(self.audit_events) + 1}"
        decision = evaluate_mcp_policy(definition, request, audit_ref=audit_ref)
        self.audit_events.append({"request": request.to_dict(), "decision": decision.to_dict()})
        if not decision.allowed:
            return HarnessWorkerResult(
                status="failed",
                output={"policy_observation": decision.to_dict()},
                diagnostics={"audit_ref": audit_ref},
                error=decision.reason,
            )
        return HarnessWorkerResult(
            status="succeeded",
            output={
                "tool_name": request.tool_name,
                "result": {"ok": True},
                "policy_observation": decision.to_dict(),
            },
            diagnostics={"audit_ref": audit_ref},
        )

    def _definition(self, tool_name: str) -> MCPToolDefinition:
        for tool in self.tools:
            if tool.name == tool_name:
                return tool
        raise HarnessValidationError(
            "MCP tool is not registered",
            code="unknown_mcp_tool",
            details={"code": "unknown_mcp_tool", "tool_name": tool_name},
        )


__all__ = ["FakeMCPToolPort"]
