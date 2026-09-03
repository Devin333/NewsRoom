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


_MISSING = object()
_KNOWN_REMOTE_SIDE_EFFECTS = frozenset(
    {
        "none",
        "read_only",
        "network_access",
        "writes_local_state",
        "writes_external_state",
        "external_write",
        "application_service_write",
        "publishing",
        "dangerous",
        "destructive",
        "local_write",
    }
)


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
        input_schema = _aliased_value(
            remote_tool,
            "input_schema",
            "inputSchema",
            default={},
        )
        if not isinstance(input_schema, dict):
            raise ValueError(f"input schema must be an object for MCP tool {remote_tool_name}")
        output_schema = _aliased_value(
            remote_tool,
            "output_schema",
            "outputSchema",
            default=None,
        )
        if output_schema is not None and not isinstance(output_schema, dict):
            raise ValueError(
                f"output schema must be an object for MCP tool {remote_tool_name}"
            )
        result_persistence = _aliased_value(
            remote_tool,
            "result_persistence",
            "resultPersistence",
            default=None,
        )
        if result_persistence is not None and not isinstance(
            result_persistence,
            dict,
        ):
            raise ValueError(
                "result persistence must be an object for MCP tool "
                f"{remote_tool_name}"
            )
        risk = _remote_risk_metadata(remote_tool)
        metadata = remote_tool.get("metadata")
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            raise ValueError(
                f"metadata must be an object for MCP tool {remote_tool_name}"
            )
        return ToolDefinition(
            name=f"mcp.{_safe_name(server.server_id)}.{_safe_name(remote_tool_name)}",
            description=str(remote_tool.get("description") or ""),
            input_schema=dict(input_schema),
            output_schema=(
                dict(output_schema) if output_schema is not None else None
            ),
            side_effect=risk["side_effect"],
            is_dangerous=risk["is_dangerous"],
            requires_approval=risk["requires_approval"],
            timeout_seconds=server.timeout_seconds,
            max_result_bytes=remote_tool.get("max_result_bytes", 1_000_000),
            concurrency_safe=bool(remote_tool.get("concurrency_safe", False)),
            required_secret_names=_string_list(
                remote_tool.get("required_secret_names", []),
                "required_secret_names",
                remote_tool_name,
            ),
            version=str(remote_tool.get("version") or "1.0.0").strip(),
            result_persistence=result_persistence,
            metadata={
                "source": "mcp",
                "server_id": server.server_id,
                "server_name": server.name,
                "remote_tool_name": remote_tool_name,
                **metadata,
                "risk_metadata_valid": risk["valid"],
                "risk_metadata_source": "remote_untrusted",
                "risk_metadata_reason": risk["reason"],
            },
        )


def _remote_risk_metadata(remote_tool: dict[str, Any]) -> dict[str, Any]:
    """Normalize untrusted MCP risk metadata with a fail-closed default."""

    side_effect = remote_tool.get("side_effect", _MISSING)
    dangerous = remote_tool.get("is_dangerous", _MISSING)
    approval = remote_tool.get("requires_approval", _MISSING)
    missing = [
        name
        for name, value in (
            ("side_effect", side_effect),
            ("is_dangerous", dangerous),
            ("requires_approval", approval),
        )
        if value is _MISSING
    ]
    valid = (
        not missing
        and isinstance(side_effect, str)
        and side_effect.strip().casefold() in _KNOWN_REMOTE_SIDE_EFFECTS
        and type(dangerous) is bool
        and type(approval) is bool
    )
    if valid:
        return {
            "side_effect": side_effect.strip().casefold(),
            "is_dangerous": dangerous,
            "requires_approval": approval,
            "valid": True,
            "reason": "observed",
        }
    reason = "missing" if missing else "invalid"
    return {
        "side_effect": "dangerous",
        "is_dangerous": True,
        "requires_approval": True,
        "valid": False,
        "reason": reason,
    }


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip())
    return safe.strip("_") or "unnamed"


def _aliased_value(
    value: dict[str, Any],
    snake_name: str,
    camel_name: str,
    *,
    default: Any,
) -> Any:
    has_snake = snake_name in value
    has_camel = camel_name in value
    if has_snake and has_camel and value[snake_name] != value[camel_name]:
        raise ValueError(
            f"conflicting MCP tool fields: {snake_name} and {camel_name}"
        )
    if has_snake:
        return value[snake_name]
    if has_camel:
        return value[camel_name]
    return default


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
