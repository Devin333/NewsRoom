from typing import Any

from core.framework.tools import (
    MappingSecretProvider,
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


def test_mcp_adapter_uses_executor_secret_provider_instead_of_environment(monkeypatch) -> None:
    monkeypatch.setenv("MCP_TOKEN", "env-secret-should-not-be-used")
    client = _SecretAwareMCPClient()
    adapter = MCPToolAdapter(client)
    server = MCPServerConfig(
        server_id="secret-server",
        name="Secret MCP",
        transport="in_memory",
    )
    registry = ToolRegistry()

    definitions = adapter.register_tools(registry, server)
    observation = ToolExecutor(
        registry,
        secret_provider=MappingSecretProvider({"MCP_TOKEN": "mapping-secret"}),
    ).execute(
        ToolCall(
            tool_name="mcp.secret_server.secure_echo",
            arguments={"message": "hello"},
        ),
        ToolPolicy(allowed_tools=["mcp.secret_server.secure_echo"], allow_mcp_tools=True),
    )

    assert definitions[0].required_secret_names == ["MCP_TOKEN"]
    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output == {"echo": "hello", "origin": "provider"}
    assert client.calls == [
        (
            "secret-server",
            "secure_echo",
            {"message": "hello", "_secrets": {"MCP_TOKEN": "mapping-secret"}},
        )
    ]


def test_mcp_adapter_registers_server_metadata_for_inspection() -> None:
    client = _InMemoryMCPClient()
    adapter = MCPToolAdapter(client)
    server = MCPServerConfig(
        server_id="fixture-server",
        name="Fixture MCP",
        transport="in_memory",
    )
    registry = ToolRegistry()

    definitions = adapter.register_tools(registry, server)
    definition = definitions[0]

    assert definition.metadata["source"] == "mcp"
    assert definition.metadata["server_id"] == "fixture-server"
    assert definition.metadata["server_name"] == "Fixture MCP"
    assert definition.metadata["remote_tool_name"] == "echo"


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


class _SecretAwareMCPClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def list_tools(self, server: MCPServerConfig) -> list[dict[str, Any]]:
        return [
            {
                "name": "secure_echo",
                "description": "Echo with a runtime-injected secret.",
                "input_schema": {
                    "required": ["message"],
                    "properties": {"message": {"type": "string"}},
                    "additionalProperties": False,
                },
                "required_secret_names": ["MCP_TOKEN"],
            }
        ]

    def call_tool(
        self,
        server: MCPServerConfig,
        remote_tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        captured = {
            key: dict(value) if isinstance(value, dict) else value
            for key, value in arguments.items()
        }
        self.calls.append((server.server_id, remote_tool_name, captured))
        origin = (
            "provider"
            if arguments.get("_secrets", {}).get("MCP_TOKEN") == "mapping-secret"
            else "unexpected"
        )
        return {"echo": arguments["message"], "origin": origin}
