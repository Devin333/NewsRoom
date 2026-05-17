from __future__ import annotations

from newsroom_sdk.models import JsonDict
from newsroom_sdk.transport import HttpTransport, quote_path_segment


class MCPResource:
    def __init__(self, transport: HttpTransport) -> None:
        self.transport = transport

    def catalog(self) -> JsonDict:
        return self.transport.request("GET", "/api/v1/mcp/catalog")

    def manifest(self) -> JsonDict:
        return self.transport.request("GET", "/api/v1/mcp/manifest")

    def capabilities(self) -> JsonDict:
        return self.transport.request("GET", "/api/v1/mcp/capabilities")

    def call_tool(self, name: str, arguments: JsonDict | None = None) -> JsonDict:
        return self.transport.request(
            "POST",
            f"/api/v1/mcp/tools/{quote_path_segment(name)}/call",
            json={"arguments": arguments or {}},
        )

    def read_resource(self, uri: str) -> JsonDict:
        return self.transport.request(
            "POST",
            "/api/v1/mcp/resources/read",
            json={"uri": uri},
        )

    def get_prompt(self, name: str, arguments: JsonDict | None = None) -> JsonDict:
        return self.transport.request(
            "POST",
            f"/api/v1/mcp/prompts/{quote_path_segment(name)}/get",
            json={"arguments": arguments or {}},
        )
