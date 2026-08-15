from __future__ import annotations

import pytest

from framework.harness import FakeMCPToolPort, MCPToolDefinition, MCPToolRequest
from framework.harness.control_plane.errors import HarnessValidationError


def test_mcp_side_effect_request_cannot_self_authorize_through_metadata() -> None:
    mcp = FakeMCPToolPort()
    result = mcp.call_tool(
        MCPToolRequest(
            tool_name="artifact.write",
            arguments={"value": 1},
            metadata={"approved": True},
        )
    )

    assert result.status == "failed"
    assert result.output["policy_observation"]["approval_status"] == "required"
    assert result.error == "side effect tool requires Harness side-effect authorization"
    assert mcp.audit_events[0]["decision"]["allowed"] is False
    assert "approved" not in mcp.audit_events[0]["request"]


def test_mcp_read_only_request_does_not_require_side_effect_authorization() -> None:
    mcp = FakeMCPToolPort()
    result = mcp.call_tool(
        MCPToolRequest(tool_name="search.read", arguments={"query": "graph"})
    )

    assert result.status == "succeeded"
    assert result.output["policy_observation"]["allowed"] is True
    assert result.output["policy_observation"]["approval_status"] == "not_required"
    assert result.diagnostics["audit_ref"].startswith("audit://mcp/")


def test_mcp_side_effect_without_human_approval_still_requires_harness_authority() -> (
    None
):
    mcp = FakeMCPToolPort(
        tools=(
            MCPToolDefinition(
                name="cache.invalidate",
                side_effect=True,
                requires_approval=False,
            ),
        )
    )

    result = mcp.call_tool(MCPToolRequest(tool_name="cache.invalidate"))

    assert result.status == "failed"
    assert result.output["policy_observation"] == {
        "allowed": False,
        "approval_status": "not_required",
        "reason": "side effect tool requires Harness side-effect authorization",
        "audit_ref": "audit://mcp/1",
    }


def test_mcp_unknown_tool_fails_closed() -> None:
    mcp = FakeMCPToolPort()

    with pytest.raises(HarnessValidationError) as captured:
        mcp.call_tool(MCPToolRequest(tool_name="unknown.write"))

    assert captured.value.code == "unknown_mcp_tool"
    assert captured.value.details == {
        "code": "unknown_mcp_tool",
        "tool_name": "unknown.write",
    }
