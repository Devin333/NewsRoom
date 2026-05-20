from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from interfaces.services.mcp_service import MCPApplicationService


JSONRPC_VERSION = "2.0"


def handle_jsonrpc_request(
    request: dict[str, Any],
    *,
    service: MCPApplicationService | None = None,
) -> dict[str, Any] | None:
    request_id = request.get("id")
    if request_id is None:
        return None
    method = request.get("method")
    params = request.get("params") or {}
    service = service or MCPApplicationService()

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


def run_stdio(
    *,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
    service: MCPApplicationService | None = None,
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
                response = handle_jsonrpc_request(request, service=service)
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
