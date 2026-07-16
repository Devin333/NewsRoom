from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from framework.events import (
    EventTelemetry,
    TelemetryInstrumentationScope,
    TelemetryResource,
    TelemetrySpanLink,
    TracePropagationError,
    W3CSpanContext,
    W3CTracePropagator,
    attach_trace_context,
    default_event_telemetry,
    reset_trace_context,
)
from interfaces.services.mcp_service import MCPApplicationService


JSONRPC_VERSION = "2.0"
_DEFAULT_MCP_PROPAGATOR = W3CTracePropagator()
_DEFAULT_MCP_TELEMETRY = default_event_telemetry(
    resource=TelemetryResource(service_name="newsroom-mcp"),
    scope=TelemetryInstrumentationScope(name="interfaces.mcp", version="1"),
)


def handle_jsonrpc_request(
    request: dict[str, Any],
    *,
    service: MCPApplicationService | None = None,
    trace_propagator: W3CTracePropagator | None = None,
    telemetry: EventTelemetry | None = None,
) -> dict[str, Any] | None:
    request_id = request.get("id")
    if request_id is None:
        return None
    method = request.get("method")
    params = request.get("params") or {}
    service = service or MCPApplicationService()
    actual_propagator = trace_propagator or _DEFAULT_MCP_PROPAGATOR
    actual_telemetry = telemetry or _DEFAULT_MCP_TELEMETRY
    try:
        extracted = actual_propagator.extract_span(_mcp_trace_carrier(params))
        local_context = extracted.child().context
        propagation_result = "accepted" if extracted.accepted_remote else "restarted"
    except TracePropagationError:
        extracted = None
        local_context = W3CSpanContext.root()
        propagation_result = "invalid"
    link = TelemetrySpanLink.from_context(
        extracted.remote_context if extracted is not None else None,
        relationship="mcp_request",
    )
    span_scope = actual_telemetry.start_span(
        "newsroom.mcp.server",
        attributes={
            "newsroom.component": "mcp",
            "newsroom.operation": "request",
            "newsroom.transport": "mcp",
            "newsroom.propagation.result": propagation_result,
        },
        links=(link,),
    )
    span_scope.__enter__()
    trace_token = attach_trace_context(local_context)

    try:
        if method == "initialize":
            return _success(
                request_id,
                {
                    "serverInfo": {"name": "NewsRoom", "version": "0.1.0"},
                    "capabilities": {
                        "tools": {},
                        "resources": {},
                        "prompts": {},
                        "capabilityManifest": {
                            "version": "1.0",
                            "method": "capabilities/list",
                        },
                    },
                },
            )
        if method == "tools/list":
            catalog = service.catalog().to_dict()
            return _success(request_id, {"tools": catalog["tools"]})
        if method == "capabilities/list":
            return _success(request_id, service.capability_manifest().to_dict())
        if method == "resources/list":
            catalog = service.catalog().to_dict()
            return _success(request_id, {"resources": catalog["resources"]})
        if method == "resources/read":
            uri = str(params.get("uri") or "")
            if not uri:
                return _error(request_id, -32602, "resources/read uri is required")
            result = service.read_resource(uri)
            return _success(request_id, result.to_dict())
        if method == "prompts/list":
            catalog = service.catalog().to_dict()
            return _success(request_id, {"prompts": catalog["prompts"]})
        if method == "prompts/get":
            prompt_name = str(params.get("name") or "")
            arguments = params.get("arguments") or {}
            if not prompt_name:
                return _error(request_id, -32602, "prompts/get name is required")
            if not isinstance(arguments, dict):
                return _error(request_id, -32602, "prompts/get arguments must be an object")
            result = service.get_prompt(prompt_name, arguments)
            return _success(request_id, result.to_dict())
        if method == "tools/call":
            tool_name = str(params.get("name") or "")
            arguments = params.get("arguments") or {}
            if not isinstance(arguments, dict):
                return _error(request_id, -32602, "tools/call arguments must be an object")
            result = service.call_tool(tool_name, arguments)
            return _success(request_id, result.to_dict())
        return _error(request_id, -32601, f"method not found: {method}")
    except Exception as exc:
        return _error(request_id, -32603, f"{type(exc).__name__}: {exc}")
    finally:
        reset_trace_context(trace_token)
        span_scope.__exit__(None, None, None)
        actual_telemetry.add_counter(
            "trace_propagation_total",
            labels={"boundary": "mcp", "result": propagation_result},
        )


def run_stdio(
    *,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
    service: MCPApplicationService | None = None,
    trace_propagator: W3CTracePropagator | None = None,
    telemetry: EventTelemetry | None = None,
) -> None:
    actual_input = input_stream if input_stream is not None else sys.stdin
    actual_output = output_stream if output_stream is not None else sys.stdout
    service = service or MCPApplicationService()

    for line in actual_input:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                response = _error(None, -32600, "request must be a JSON object")
            else:
                response = handle_jsonrpc_request(
                    request,
                    service=service,
                    trace_propagator=trace_propagator,
                    telemetry=telemetry,
                )
        except json.JSONDecodeError as exc:
            response = _error(None, -32700, f"parse error: {exc.msg}")
        if response is not None:
            actual_output.write(json.dumps(response, ensure_ascii=False, sort_keys=True) + "\n")
            actual_output.flush()


def _success(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _mcp_trace_carrier(params: Any) -> dict[str, str]:
    if not isinstance(params, dict):
        return {}
    metadata = params.get("_meta")
    if not isinstance(metadata, dict):
        return {}
    carrier: dict[str, str] = {}
    for key in ("traceparent", "tracestate", "baggage"):
        value = metadata.get(key)
        if isinstance(value, str):
            carrier[key] = value
    return carrier
