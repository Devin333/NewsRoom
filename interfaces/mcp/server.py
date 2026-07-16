from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, TypeVar

from framework.events import W3CTracePropagator, trace_context_scope
from interfaces.services.mcp_service import MCPApplicationService


_T = TypeVar("_T")


class NewsMCPServerAdapter:
    """Thin inbound MCP adapter over the application service.

    This class intentionally does not own a production transport loop; stdio and
    HTTP adapters delegate here so catalog, tools, resources, and prompts stay
    service-sourced.
    """

    def __init__(
        self,
        service: MCPApplicationService | None = None,
        *,
        trace_propagator: W3CTracePropagator | None = None,
    ) -> None:
        self.service = service or MCPApplicationService()
        self._trace_propagator = trace_propagator or W3CTracePropagator()

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
        *,
        trace_carrier: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        return self._with_trace(
            trace_carrier,
            lambda: self.service.call_tool(name, arguments or {}).to_dict(),
        )

    def list_resources(self) -> dict[str, Any]:
        return {"resources": self.catalog()["resources"]}

    def read_resource(
        self,
        uri: str,
        *,
        trace_carrier: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        return self._with_trace(
            trace_carrier,
            lambda: self.service.read_resource(uri).to_dict(),
        )

    def list_prompts(self) -> dict[str, Any]:
        return {"prompts": self.catalog()["prompts"]}

    def get_prompt(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        trace_carrier: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        return self._with_trace(
            trace_carrier,
            lambda: self.service.get_prompt(name, arguments or {}).to_dict(),
        )

    def _with_trace(
        self,
        carrier: Mapping[str, str] | None,
        call: Callable[[], _T],
    ) -> _T:
        local_context = self._trace_propagator.extract_span(carrier or {}).child().context
        with trace_context_scope(local_context):
            return call()


def create_mcp_server(
    service: MCPApplicationService | None = None,
    *,
    trace_propagator: W3CTracePropagator | None = None,
) -> NewsMCPServerAdapter:
    return NewsMCPServerAdapter(
        service=service,
        trace_propagator=trace_propagator,
    )
