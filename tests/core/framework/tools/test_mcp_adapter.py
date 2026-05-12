from typing import Any

from core.framework.tools import (
    MCPServerConfig,
    MCPToolAdapter,
    ToolCall,
    ToolExecutor,
    ToolPolicy,
    ToolRegistry,
    ToolStatus,
)


def test_mcp_adapter_registers_and_executes_remote_tool_through_executor() -> None:
    client = _InMemoryMCPClient()
    adapter = MCPToolAdapter(client)
    server = MCPServerConfig(
        server_id="fixture-server",
        name="Fixture MCP",
        transport="in_memory",
    )
    registry = ToolRegistry()

    definitions = adapter.register_tools(registry, server)
    observation = ToolExecutor(registry).execute(
        ToolCall(
            tool_name="mcp.fixture_server.echo",
            arguments={"message": "hello"},
        ),
        ToolPolicy(allowed_tools=["mcp.fixture_server.echo"], allow_mcp_tools=True),
    )

    assert [definition.name for definition in definitions] == ["mcp.fixture_server.echo"]
    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output == {"echo": "hello", "server_id": "fixture-server"}
    assert client.calls == [("fixture-server", "echo", {"message": "hello"})]


def test_mcp_adapter_honors_disabled_server() -> None:
    client = _InMemoryMCPClient()
    adapter = MCPToolAdapter(client)
    server = MCPServerConfig(
        server_id="fixture",
        name="Fixture MCP",
        transport="in_memory",
        enabled=False,
    )

    assert adapter.list_tools(server) == []


class _InMemoryMCPClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def list_tools(self, server: MCPServerConfig) -> list[dict[str, Any]]:
        return [
            {
                "name": "echo",
                "description": "Echo a message",
                "input_schema": {
                    "required": ["message"],
                    "properties": {"message": {"type": "string"}},
                    "additionalProperties": False,
                },
                "concurrency_safe": True,
            }
        ]

    def call_tool(
        self,
        server: MCPServerConfig,
        remote_tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append((server.server_id, remote_tool_name, dict(arguments)))
        return {"echo": arguments["message"], "server_id": server.server_id}
