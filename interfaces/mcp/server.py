from __future__ import annotations

from typing import Any

from interfaces.services.mcp_service import MCPApplicationService


class NewsMCPServerAdapter:
    """Thin inbound MCP adapter over the application service.

    This class intentionally does not own a production transport loop; stdio and
    HTTP adapters delegate here so catalog, tools, resources, and prompts stay
    service-sourced.
    """

    def __init__(self, service: MCPApplicationService | None = None) -> None:
        self.service = service or MCPApplicationService()

    def catalog(self) -> dict[str, Any]:
        return self.service.catalog().to_dict()

    def manifest(self) -> dict[str, Any]:
        return self.service.capability_manifest().to_dict()

    def list_tools(self) -> dict[str, Any]:
        return {"tools": self.catalog()["tools"]}

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.service.call_tool(name, arguments or {}).to_dict()

    def list_resources(self) -> dict[str, Any]:
        return {"resources": self.catalog()["resources"]}

    def read_resource(self, uri: str) -> dict[str, Any]:
        return self.service.read_resource(uri).to_dict()

    def list_prompts(self) -> dict[str, Any]:
        return {"prompts": self.catalog()["prompts"]}

    def get_prompt(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.service.get_prompt(name, arguments or {}).to_dict()


def create_mcp_server(service: MCPApplicationService | None = None) -> NewsMCPServerAdapter:
    return NewsMCPServerAdapter(service=service)
