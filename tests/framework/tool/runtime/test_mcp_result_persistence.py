from __future__ import annotations

import pytest

from framework.tool import (
    MCPServerConfig,
    MCPToolAdapter,
    ToolCall,
    ToolDefinitionError,
    ToolExecutor,
    ToolPolicy,
    ToolResultEnvelope,
)
from framework.tool.registry import ToolRegistry


class _RemoteClient:
    def __init__(self, remote_tool, response) -> None:
        self.remote_tool = remote_tool
        self.response = response
        self.calls = 0

    def list_tools(self, _server):
        return [self.remote_tool]

    def call_tool(self, _server, remote_tool_name, arguments):
        assert remote_tool_name == self.remote_tool["name"]
        assert arguments == {}
        self.calls += 1
        return self.response


def _server() -> MCPServerConfig:
    return MCPServerConfig(
        server_id="remote-search",
        name="Remote Search",
        transport="in_memory",
    )


def test_outbound_mcp_propagates_result_contract_into_tool_materialization_model() -> None:
    remote = {
        "name": "search",
        "version": "2.3.4",
        "inputSchema": {"type": "object", "properties": {}},
        "outputSchema": {
            "type": "object",
            "properties": {
                "items": {"type": "array"},
                "next_cursor": {"type": "string"},
                "has_more": {"type": "boolean"},
            },
            "required": ["items", "next_cursor", "has_more"],
        },
        "resultPersistence": {
            "media_type": "application/json",
            "control_fields": ["next_cursor", "has_more"],
            "artifact_class": "intermediate",
            "retention_class": "run",
            "sensitivity": "internal",
            "context_policy": "summary_only",
        },
    }
    response = {
        "items": [{"id": index} for index in range(10)],
        "next_cursor": "cursor-2",
        "has_more": True,
    }
    client = _RemoteClient(remote, response)
    registry = ToolRegistry()
    definition = MCPToolAdapter(client).register_tools(registry, _server())[0]

    observation = ToolExecutor(
        registry,
        defer_result_persistence=True,
    ).execute(
        ToolCall(tool_name=definition.name, call_id="mcp-call-1"),
        ToolPolicy(
            allowed_tools=[definition.name],
            allow_mcp_tools=True,
            require_explicit_allowlist=True,
        ),
    )
    envelope = ToolResultEnvelope.from_observation(observation, definition)

    assert definition.output_schema == remote["outputSchema"]
    assert definition.version == "2.3.4"
    assert definition.result_persistence.control_fields == (
        "has_more",
        "next_cursor",
    )
    assert envelope.control_projection["next_cursor"] == "cursor-2"
    assert envelope.control_projection["has_more"] is True
    assert "items" not in envelope.control_projection
    assert client.calls == 1


def test_outbound_mcp_preserves_explicit_empty_output_schema() -> None:
    remote = {
        "name": "search",
        "inputSchema": {},
        "outputSchema": {},
    }

    definition = MCPToolAdapter(_RemoteClient(remote, {})).list_tools(_server())[0]

    assert definition.input_schema == {}
    assert definition.output_schema == {}


def test_outbound_mcp_rejects_conflicting_schema_aliases() -> None:
    remote = {
        "name": "search",
        "input_schema": {"type": "object"},
        "inputSchema": {},
    }

    with pytest.raises(ValueError, match="conflicting MCP tool fields"):
        MCPToolAdapter(_RemoteClient(remote, {})).list_tools(_server())


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("outputSchema", [], "output schema must be an object"),
        ("resultPersistence", [], "result persistence must be an object"),
    ],
)
def test_outbound_mcp_rejects_invalid_remote_result_contract(
    field,
    value,
    message,
) -> None:
    remote = {
        "name": "search",
        "inputSchema": {"type": "object"},
        field: value,
    }

    with pytest.raises(ValueError, match=message):
        MCPToolAdapter(_RemoteClient(remote, {})).list_tools(_server())


def test_outbound_mcp_rejects_unregistered_control_field() -> None:
    remote = {
        "name": "search",
        "inputSchema": {"type": "object"},
        "outputSchema": {
            "type": "object",
            "properties": {"items": {"type": "array"}},
        },
        "resultPersistence": {"control_fields": ["route"]},
    }

    with pytest.raises(ToolDefinitionError, match="invalid field"):
        MCPToolAdapter(_RemoteClient(remote, {})).list_tools(_server())
