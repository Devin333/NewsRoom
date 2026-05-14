import pytest

from core.framework.llm import LLMToolCallParseError, LLMToolSchemaError
from core.framework.llm.tool_adapters import parse_openai_tool_calls, to_openai_tools


def test_tool_definition_exports_openai_compatible_schema() -> None:
    tools = [
        {
            "name": "memory.search",
            "description": "Search memory",
            "input_schema": {
                "type": "object",
                "required": ["query"],
                "properties": {"query": {"type": "string"}},
            },
        }
    ]

    assert to_openai_tools(tools) == [
        {
            "type": "function",
            "function": {
                "name": "memory_search",
                "description": "Search memory",
                "parameters": {
                    "type": "object",
                    "required": ["query"],
                    "properties": {"query": {"type": "string"}},
                },
            },
        }
    ]


def test_tool_definition_without_description_is_rejected() -> None:
    with pytest.raises(LLMToolSchemaError, match="non-empty description"):
        to_openai_tools([{"name": "memory.search"}])


def test_tool_schema_rejects_unsupported_parameter_type() -> None:
    with pytest.raises(LLMToolSchemaError, match="unsupported parameter type"):
        to_openai_tools(
            [
                {
                    "name": "memory.search",
                    "description": "Search memory",
                    "input_schema": {
                        "type": "object",
                        "properties": {"query": {"type": "date"}},
                    },
                }
            ]
        )


def test_parse_openai_tool_call_maps_provider_name_to_internal_name() -> None:
    calls = parse_openai_tool_calls(
        [
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "memory_search",
                    "arguments": "{\"query\":\"chips\"}",
                },
            }
        ],
        [{"name": "memory.search", "description": "Search memory"}],
    )

    assert len(calls) == 1
    assert calls[0].tool_name == "memory.search"
    assert calls[0].arguments == {"query": "chips"}
    assert calls[0].provider_tool_call_id == "call_1"


def test_parse_openai_tool_call_rejects_malformed_arguments() -> None:
    with pytest.raises(LLMToolCallParseError, match="not valid JSON"):
        parse_openai_tool_calls(
            [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "memory_search", "arguments": "not json"},
                }
            ],
            [{"name": "memory.search", "description": "Search memory"}],
        )
