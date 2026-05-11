from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any

from core.framework.llm.models import LLMToolCall


class LLMToolSchemaError(ValueError):
    """Raised when tool schemas cannot be adapted safely."""


class LLMToolCallParseError(ValueError):
    """Raised when provider tool calls cannot be parsed safely."""


_UNSAFE_TOOL_NAME_CHARS = re.compile(r"[^A-Za-z0-9_-]+")


def to_openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    name_map = openai_tool_name_map(tools)
    adapted_tools = []
    for tool in tools:
        if _is_openai_tool(tool):
            adapted_tools.append(deepcopy(tool))
            continue

        internal_name = _internal_tool_name(tool)
        provider_name = name_map[internal_name]
        input_schema = _openai_parameters(tool.get("input_schema"))
        adapted_tools.append(
            {
                "type": "function",
                "function": {
                    "name": provider_name,
                    "description": str(tool.get("description") or ""),
                    "parameters": deepcopy(input_schema),
                },
            }
        )
    return adapted_tools


def openai_tool_name_map(tools: list[dict[str, Any]]) -> dict[str, str]:
    internal_to_provider: dict[str, str] = {}
    provider_to_internal: dict[str, str] = {}
    for tool in tools:
        if _is_openai_tool(tool):
            provider_name = _openai_function_name(tool)
            metadata = tool.get("metadata") or {}
            if not isinstance(metadata, dict):
                metadata = {}
            internal_name = str(metadata.get("internal_name") or provider_name)
        else:
            internal_name = _internal_tool_name(tool)
            provider_name = _provider_safe_tool_name(internal_name)

        existing_internal = provider_to_internal.get(provider_name)
        if existing_internal is not None and existing_internal != internal_name:
            raise LLMToolSchemaError(
                f"tool names collide after provider adaptation: {existing_internal}, {internal_name}"
            )
        internal_to_provider[internal_name] = provider_name
        provider_to_internal[provider_name] = internal_name
    return internal_to_provider


def parse_openai_tool_calls(
    raw_tool_calls: Any,
    tools: list[dict[str, Any]],
) -> list[LLMToolCall]:
    if raw_tool_calls in (None, []):
        return []
    if not isinstance(raw_tool_calls, list):
        raise LLMToolCallParseError("provider tool_calls must be a list")

    provider_to_internal = {
        provider_name: internal_name
        for internal_name, provider_name in openai_tool_name_map(tools).items()
    }
    parsed_calls = []
    for index, raw_tool_call in enumerate(raw_tool_calls):
        if not isinstance(raw_tool_call, dict):
            raise LLMToolCallParseError("provider tool_call must be an object")
        function = raw_tool_call.get("function") or {}
        if not isinstance(function, dict):
            raise LLMToolCallParseError("provider tool_call function must be an object")

        provider_name = function.get("name")
        if not isinstance(provider_name, str) or not provider_name:
            raise LLMToolCallParseError("provider tool_call missing function name")
        raw_arguments = function.get("arguments") or "{}"
        if not isinstance(raw_arguments, str):
            raise LLMToolCallParseError("provider tool_call arguments must be a JSON string")
        try:
            arguments = json.loads(raw_arguments)
        except json.JSONDecodeError as exc:
            raise LLMToolCallParseError("provider tool_call arguments are not valid JSON") from exc
        if not isinstance(arguments, dict):
            raise LLMToolCallParseError("provider tool_call arguments must be a JSON object")

        provider_tool_call_id = raw_tool_call.get("id")
        tool_call_id = str(provider_tool_call_id or f"tool_call_{index + 1}")
        parsed_calls.append(
            LLMToolCall(
                tool_call_id=tool_call_id,
                tool_name=provider_to_internal.get(provider_name, provider_name),
                arguments=arguments,
                raw_arguments=raw_arguments,
                provider_tool_call_id=str(provider_tool_call_id) if provider_tool_call_id else None,
                metadata={"provider_tool_name": provider_name},
            )
        )
    return parsed_calls


def _is_openai_tool(tool: dict[str, Any]) -> bool:
    return tool.get("type") == "function" and isinstance(tool.get("function"), dict)


def _openai_function_name(tool: dict[str, Any]) -> str:
    function = tool.get("function") or {}
    name = function.get("name")
    if not isinstance(name, str) or not name:
        raise LLMToolSchemaError("OpenAI-compatible function tool requires a name")
    return name


def _internal_tool_name(tool: dict[str, Any]) -> str:
    name = tool.get("name")
    if not isinstance(name, str) or not name:
        raise LLMToolSchemaError("tool schema requires a name")
    return name


def _provider_safe_tool_name(internal_name: str) -> str:
    provider_name = _UNSAFE_TOOL_NAME_CHARS.sub("_", internal_name).strip("_")
    if not provider_name:
        raise LLMToolSchemaError(f"tool name cannot be adapted: {internal_name}")
    return provider_name[:64]


def _openai_parameters(input_schema: Any) -> dict[str, Any]:
    if not isinstance(input_schema, dict) or not input_schema:
        return {"type": "object", "properties": {}}
    parameters = deepcopy(input_schema)
    parameters.setdefault("type", "object")
    parameters.setdefault("properties", {})
    return parameters
