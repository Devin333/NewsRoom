from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from framework.events import (
    TraceContext,
    W3CSpanContext,
    W3CTracePropagator,
    current_trace_context,
)
from framework.shared.attempts import current_attempt_context, derive_idempotency_key
from framework.tool.models import ToolDefinition, ToolRuntimeError
from framework.tool.registry import ToolRegistry
from framework.tool.runtime.timeout import run_with_timeout


@dataclass(frozen=True)
class MCPServerConfig:
    server_id: str
    name: str
    transport: str
    command: str | None = None
    args: list[str] = field(default_factory=list)
    url: str | None = None
    headers_env: dict[str, str] = field(default_factory=dict)
    trace_carrier: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    timeout_seconds: float = 30.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.server_id:
            raise ValueError("server_id is required")
        if not self.name:
            raise ValueError("name is required")
        if self.transport not in {"stdio", "http", "sse", "in_memory"}:
            raise ValueError(f"unsupported MCP transport: {self.transport}")


class MCPClientProtocol(Protocol):
    def list_tools(self, server: MCPServerConfig) -> list[dict[str, Any]]: ...

    def call_tool(
        self,
        server: MCPServerConfig,
        remote_tool_name: str,
        arguments: dict[str, Any],
    ) -> Any: ...


class MCPToolAdapter:
    def __init__(
        self,
        client: MCPClientProtocol,
        *,
        trace_context: TraceContext | W3CSpanContext | None = None,
        trace_propagator: W3CTracePropagator | None = None,
    ) -> None:
        self._client = client
        self._trace_context = trace_context
        self._trace_propagator = trace_propagator or W3CTracePropagator()

    def list_tools(self, server: MCPServerConfig) -> list[ToolDefinition]:
        if not server.enabled:
            return []
        outbound_server = self._outbound_server(server)
        return [
            self._definition_from_remote_tool(server, remote_tool)
            for remote_tool in _run_mcp_operation(
                lambda: self._client.list_tools(outbound_server),
                timeout_seconds=server.timeout_seconds,
                operation=f"list tools from MCP server {server.server_id}",
            )
        ]

    def register_tools(self, registry: ToolRegistry, server: MCPServerConfig) -> list[ToolDefinition]:
        definitions = self.list_tools(server)
        for definition in definitions:
            remote_tool_name = str(definition.metadata["remote_tool_name"])
            registry.register(
                definition,
                lambda args, remote_tool_name=remote_tool_name: _run_mcp_operation(
                    lambda: self._client.call_tool(
                        self._outbound_server(server),
                        remote_tool_name,
                        args,
                    ),
                    timeout_seconds=server.timeout_seconds,
                    operation=(
                        f"call MCP tool {server.server_id}.{remote_tool_name}"
                    ),
                ),
            )
        return definitions

    def _outbound_server(self, server: MCPServerConfig) -> MCPServerConfig:
        context = self._trace_context or current_trace_context()
        if context is None:
            carrier = self._trace_propagator.inject(
                W3CSpanContext.root(),
                server.trace_carrier,
            )
        else:
            span_context = (
                W3CSpanContext.from_trace_context(context)
                if isinstance(context, TraceContext)
                else context
            )
            carrier = (
                self._trace_propagator.inject(
                    span_context.child(),
                    server.trace_carrier,
                )
                if span_context is not None
                else {}
            )
        return replace(server, trace_carrier=carrier)

    def _definition_from_remote_tool(
        self,
        server: MCPServerConfig,
        remote_tool: dict[str, Any],
    ) -> ToolDefinition:
        remote_tool_name = str(remote_tool.get("name") or "")
        if not remote_tool_name:
            raise ValueError("remote MCP tool name is required")
        input_schema = remote_tool.get("input_schema") or remote_tool.get("inputSchema") or {}
        if not isinstance(input_schema, dict):
            raise ValueError(f"input schema must be an object for MCP tool {remote_tool_name}")
        return ToolDefinition(
            name=f"mcp.{_safe_name(server.server_id)}.{_safe_name(remote_tool_name)}",
            description=str(remote_tool.get("description") or ""),
            input_schema=dict(input_schema),
            side_effect=str(remote_tool.get("side_effect") or "read_only"),
            is_dangerous=bool(remote_tool.get("is_dangerous", False)),
            requires_approval=bool(remote_tool.get("requires_approval", False)),
            timeout_seconds=server.timeout_seconds,
            max_result_bytes=remote_tool.get("max_result_bytes", 1_000_000),
            concurrency_safe=bool(remote_tool.get("concurrency_safe", False)),
            required_secret_names=_string_list(
                remote_tool.get("required_secret_names", []),
                "required_secret_names",
                remote_tool_name,
            ),
            metadata={
                "source": "mcp",
                "server_id": server.server_id,
                "server_name": server.name,
                "remote_tool_name": remote_tool_name,
                **dict(remote_tool.get("metadata") or {}),
            },
        )


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip())
    return safe.strip("_") or "unnamed"


def _string_list(value: Any, field_name: str, tool_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list for MCP tool {tool_name}")
    return [str(item) for item in value]


def _run_mcp_operation(
    operation_fn: Any,
    *,
    timeout_seconds: float,
    operation: str,
) -> Any:
    parent_context = current_attempt_context()
    idempotency_key = (
        derive_idempotency_key(
            parent_context.idempotency_key,
            "mcp",
            operation,
        )
        if parent_context is not None
        else f"standalone:mcp:{operation}"
    )
    try:
        return run_with_timeout(
            operation_fn,
            timeout_seconds,
            operation=f"MCP operation during {operation}",
            idempotency_key=idempotency_key,
        )
    except ToolRuntimeError:
        raise
    except Exception as exc:
        raise ToolRuntimeError(f"MCP transport error during {operation}: {exc}") from exc
