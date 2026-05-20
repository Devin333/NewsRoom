from typing import cast

import pytest

from framework.tool import (
    RegisteredTool,
    ToolDefinition,
    ToolDefinitionError,
    ToolPolicy,
    ToolRegistry,
)
from framework.tool.models import ToolExecutorFn


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


def test_tool_definition_exports_namespace_version_and_tool_id() -> None:
    definition = ToolDefinition(name="memory.search", version="1.2.0")

    payload = definition.to_dict()

    assert definition.namespace == "memory"
    assert definition.tool_id == "memory.search@1.2.0"
    assert payload["namespace"] == "memory"
    assert payload["version"] == "1.2.0"
    assert payload["tool_id"] == "memory.search@1.2.0"


def test_tool_registry_rejects_duplicate_tool_name() -> None:
    registry = ToolRegistry()
    definition = ToolDefinition(name="artifact.load")
    registry.register(definition, lambda args: args)

    with pytest.raises(ToolDefinitionError, match="already registered"):
        registry.register(definition, lambda args: args)


def test_tool_registry_skip_duplicate_keeps_existing_registration() -> None:
    registry = ToolRegistry()
    original = ToolDefinition(name="artifact.load", description="Original")
    replacement = ToolDefinition(name="artifact.load", description="Replacement")
    registry.register(original, lambda args: {"source": "original"})

    registered = registry.register(
        replacement,
        lambda args: {"source": "replacement"},
        duplicate_policy="skip",
    )

    assert registered.definition == original
    assert registry.get("artifact.load").definition == original
    assert registry.get("artifact.load").executor({}) == {"source": "original"}


def test_tool_registry_replace_explicit_replaces_duplicate_registration() -> None:
    registry = ToolRegistry()
    original = ToolDefinition(name="artifact.load", description="Original")
    replacement = ToolDefinition(name="artifact.load", description="Replacement")
    registry.register(original, lambda args: {"source": "original"})

    registered = registry.register(
        replacement,
        lambda args: {"source": "replacement"},
        duplicate_policy="replace_explicit",
    )

    assert registered.definition == replacement
    assert registry.get("artifact.load").definition == replacement
    assert registry.get("artifact.load").executor({}) == {"source": "replacement"}


def test_tool_registry_rejects_unknown_duplicate_policy() -> None:
    registry = ToolRegistry()
    registry.register(ToolDefinition(name="artifact.load"), lambda args: args)

    with pytest.raises(ToolDefinitionError, match="unsupported duplicate policy"):
        registry.register(
            ToolDefinition(name="artifact.load"),
            lambda args: args,
            duplicate_policy="overwrite",
        )


def test_tool_registry_validate_no_conflicts_returns_ok_result() -> None:
    registry = ToolRegistry()
    registry.register(ToolDefinition(name="memory.search"), lambda args: args)
    registry.register(ToolDefinition(name="artifact.load"), lambda args: args)

    result = registry.validate_no_conflicts()

    assert result.ok is True
    assert result.errors == ()
    assert result.tool_count == 2
    assert result.to_dict() == {"ok": True, "errors": [], "tool_count": 2}


def test_tool_registry_validate_no_conflicts_reports_inconsistent_state() -> None:
    registry = ToolRegistry()
    registry.register(ToolDefinition(name="memory.search"), lambda args: args)
    registry._tools["artifact.load"] = RegisteredTool(
        definition=ToolDefinition(name="memory.search"),
        executor=cast(ToolExecutorFn, None),
    )

    result = registry.validate_no_conflicts()

    assert result.ok is False
    assert result.tool_count == 2
    assert any("does not match definition name" in error for error in result.errors)
    assert any("executor is not callable" in error for error in result.errors)


def test_tool_definition_requires_namespace() -> None:
    with pytest.raises(ToolDefinitionError, match="namespaced"):
        ToolDefinition(name="search")


def test_tool_definition_rejects_empty_namespace_segments() -> None:
    with pytest.raises(ToolDefinitionError, match="namespaced"):
        ToolDefinition(name=".search")
    with pytest.raises(ToolDefinitionError, match="namespaced"):
        ToolDefinition(name="memory.")


def test_tool_definition_requires_version() -> None:
    with pytest.raises(ToolDefinitionError, match="version is required"):
        ToolDefinition(name="memory.search", version="")


def test_tool_definition_rejects_invalid_max_result_bytes() -> None:
    with pytest.raises(ToolDefinitionError, match="max_result_bytes"):
        ToolDefinition(name="memory.search", max_result_bytes=-1)


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


def test_tool_registry_hides_mcp_tools_from_schema_by_default() -> None:
    registry = ToolRegistry()
    registry.register(ToolDefinition(name="memory.search"), lambda args: args)
    registry.register(ToolDefinition(name="mcp.fixture.echo"), lambda args: args)

    schemas = registry.export_schema_for_llm(
        "analyst",
        ToolPolicy(allowed_tools=["memory.search", "mcp.fixture.echo"]),
    )

    assert [schema["name"] for schema in schemas] == ["memory.search"]


def test_tool_registry_exposes_mcp_tools_when_policy_allows_it() -> None:
    registry = ToolRegistry()
    registry.register(ToolDefinition(name="memory.search"), lambda args: args)
    registry.register(ToolDefinition(name="mcp.fixture.echo"), lambda args: args)

    schemas = registry.export_schema_for_llm(
        "analyst",
        ToolPolicy(
            allowed_tools=["memory.search", "mcp.fixture.echo"],
            allow_mcp_tools=True,
        ),
    )

    assert [schema["name"] for schema in schemas] == ["memory.search", "mcp.fixture.echo"]


def test_tool_registry_preserves_legacy_schema_export_allowed_list() -> None:
    registry = ToolRegistry()
    registry.register(ToolDefinition(name="memory.search"), lambda args: args)
    registry.register(ToolDefinition(name="artifact.load"), lambda args: args)

    schemas = registry.export_schema_for_llm(["artifact.load"])

    assert [schema["name"] for schema in schemas] == ["artifact.load"]
