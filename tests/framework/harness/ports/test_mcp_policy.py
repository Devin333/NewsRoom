from __future__ import annotations

from framework.harness import FakeMCPToolPort, MCPToolRequest


def test_mcp_side_effect_request_is_rejected_without_approval() -> None:
    mcp = FakeMCPToolPort()
    result = mcp.call_tool(MCPToolRequest(tool_name="artifact.write", arguments={"value": 1}, approved=False))

    assert result.status == "failed"
    assert result.output["policy_decision"]["approval_status"] == "required"
    assert mcp.audit_events[0]["decision"]["allowed"] is False


def test_mcp_side_effect_request_runs_after_approval() -> None:
    mcp = FakeMCPToolPort()
    result = mcp.call_tool(MCPToolRequest(tool_name="artifact.write", arguments={"value": 1}, approved=True))

    assert result.status == "succeeded"
    assert result.output["policy_decision"]["allowed"] is True
    assert result.diagnostics["audit_ref"].startswith("audit://mcp/")
