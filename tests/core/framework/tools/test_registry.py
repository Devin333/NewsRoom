import pytest

from core.framework.tools import ToolDefinition, ToolDefinitionError, ToolRegistry


def test_tool_registry_registers_namespaced_tool() -> None:
    registry = ToolRegistry()
    definition = ToolDefinition(
        name="memory.search",
        description="Search memory",
        input_schema={"required": ["query"]},
    )

    registry.register(definition, lambda args: {"items": [args["query"]]})

    assert registry.get("memory.search").definition == definition
    assert registry.export_schema_for_llm(["memory.search"])[0]["name"] == "memory.search"


def test_tool_registry_rejects_duplicate_tool_name() -> None:
    registry = ToolRegistry()
    definition = ToolDefinition(name="artifact.load")
    registry.register(definition, lambda args: args)

    with pytest.raises(ToolDefinitionError, match="already registered"):
        registry.register(definition, lambda args: args)


def test_tool_definition_requires_namespace() -> None:
    with pytest.raises(ToolDefinitionError, match="namespaced"):
        ToolDefinition(name="search")
