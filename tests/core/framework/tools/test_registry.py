import pytest

from core.framework.tools import ToolDefinition, ToolDefinitionError, ToolPolicy, ToolRegistry


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


def test_tool_registry_lists_tools_for_agent_using_policy() -> None:
    registry = ToolRegistry()
    registry.register(ToolDefinition(name="memory.search"), lambda args: args)
    registry.register(ToolDefinition(name="artifact.load"), lambda args: args)
    registry.register(ToolDefinition(name="report.render"), lambda args: args)

    definitions = registry.list_tools_for_agent(
        "analyst",
        ToolPolicy(
            allowed_tools=["memory.search", "artifact.load", "report.render"],
            blocked_tools=["artifact.load"],
        ),
    )

    assert [definition.name for definition in definitions] == ["memory.search", "report.render"]


def test_tool_registry_hides_dangerous_tools_from_agent_schema_by_default() -> None:
    registry = ToolRegistry()
    registry.register(ToolDefinition(name="memory.search"), lambda args: args)
    registry.register(ToolDefinition(name="system.command", is_dangerous=True), lambda args: args)

    schemas = registry.export_schema_for_llm(
        "analyst",
        ToolPolicy(allowed_tools=["memory.search", "system.command"]),
    )

    assert [schema["name"] for schema in schemas] == ["memory.search"]


def test_tool_registry_exposes_dangerous_tools_when_policy_allows_it() -> None:
    registry = ToolRegistry()
    registry.register(ToolDefinition(name="memory.search"), lambda args: args)
    registry.register(ToolDefinition(name="system.command", is_dangerous=True), lambda args: args)

    schemas = registry.export_schema_for_llm(
        "operator",
        ToolPolicy(
            allowed_tools=["memory.search", "system.command"],
            allow_dangerous_tools=True,
        ),
    )

    assert [schema["name"] for schema in schemas] == ["memory.search", "system.command"]


def test_tool_registry_preserves_legacy_schema_export_allowed_list() -> None:
    registry = ToolRegistry()
    registry.register(ToolDefinition(name="memory.search"), lambda args: args)
    registry.register(ToolDefinition(name="artifact.load"), lambda args: args)

    schemas = registry.export_schema_for_llm(["artifact.load"])

    assert [schema["name"] for schema in schemas] == ["artifact.load"]
