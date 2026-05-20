import time
from typing import Any

from framework.tool import (
    MCPServerConfig,
    MCPToolAdapter,
    REDACTED_VALUE,
    ToolCall,
    ToolDefinition,
    ToolExecutor,
    ToolPolicy,
    ToolRegistry,
    ToolRuntimeError,
    ToolStatus,
    ToolTestCase,
    ToolTestRunner,
    ToolTimeoutError,
    build_tool_catalog,
)
from framework.tool.runtime.batch_executor import ToolBatchExecutor


def test_duplicate_tool_error_includes_old_and_new_namespaces() -> None:
    registry = ToolRegistry()
    registry.register(ToolDefinition(name="memory.search"), lambda args: args)

    try:
        registry.register(ToolDefinition(name="memory.search"), lambda args: args)
    except Exception as exc:
        message = str(exc)
    else:
        raise AssertionError("duplicate registration should fail")

    assert "already registered" in message
    assert "old namespace=memory" in message
    assert "new namespace=memory" in message


def test_duplicate_replace_alias_is_explicit_and_replaces() -> None:
    registry = ToolRegistry()
    registry.register(ToolDefinition(name="artifact.load", description="old"), lambda args: "old")

    registry.register(
        ToolDefinition(name="artifact.load", description="new"),
        lambda args: "new",
        duplicate_policy="replace",
    )

    assert registry.get("artifact.load").definition.description == "new"
    assert registry.get("artifact.load").executor({}) == "new"


def test_catalog_reports_duplicate_leaf_name_risk() -> None:
    registry = ToolRegistry()
    registry.register(ToolDefinition(name="local.search"), lambda args: args)
    registry.register(ToolDefinition(name="mcp.fixture.search"), lambda args: args)

    catalog = build_tool_catalog(registry)
    payload = catalog.to_dict()

    assert catalog.duplicate_risk_count == 2
    assert payload["duplicate_risk_namespaces"] == ["local", "mcp"]
    assert payload["duplicate_risk_count"] == 2


def test_tool_executor_applies_schema_defaults_before_invocation() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="memory.search",
            input_schema={
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 5},
                },
                "additionalProperties": False,
            },
        ),
        lambda args: {"query": args["query"], "limit": args["limit"]},
    )

    observation = ToolExecutor(registry).execute(
        ToolCall(tool_name="memory.search", arguments={"query": "chips"}),
        ToolPolicy(allowed_tools=["memory.search"]),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output == {"query": "chips", "limit": 5}


def test_dangerous_tool_default_deny_covers_named_privileged_tools() -> None:
    calls: list[str] = []
    registry = ToolRegistry()
    for tool_name in [
        "system.execute",
        "file.write",
        "file.delete",
        "postgres.query",
        "http.request",
        "publish.external",
        "report.publish",
        "postgres.save_report",
        "notification.send",
        "notification.webhook",
    ]:
        registry.register(
            ToolDefinition(
                name=tool_name,
                is_dangerous=True,
                side_effect="external_write",
                input_schema={"required": [], "properties": {}, "additionalProperties": False},
            ),
            lambda args, tool_name=tool_name: calls.append(tool_name),
        )

    executor = ToolExecutor(registry)
    observations = [
        executor.execute(
            ToolCall(tool_name=tool_name, arguments={}),
            ToolPolicy(allowed_tools=[tool_name]),
        )
        for tool_name in [definition.name for definition in registry.list_tools()]
    ]

    assert calls == []
    assert {observation.status for observation in observations} == {ToolStatus.BLOCKED}
    assert all(observation.result.error_type == "ToolPermissionError" for observation in observations)


def test_default_dangerous_named_tool_is_hidden_from_agent_schema_without_marker() -> None:
    registry = ToolRegistry()
    registry.register(ToolDefinition(name="http.request"), lambda args: args)
    registry.register(ToolDefinition(name="memory.search"), lambda args: args)

    hidden = registry.export_schema_for_llm(
        "analyst",
        ToolPolicy(allowed_tools=["http.request", "memory.search"]),
    )
    exposed = registry.export_schema_for_llm(
        "operator",
        ToolPolicy(
            allowed_tools=["http.request", "memory.search"],
            allow_dangerous_tools=True,
        ),
    )

    assert [schema["name"] for schema in hidden] == ["memory.search"]
    assert [schema["name"] for schema in exposed] == ["http.request", "memory.search"]


def test_observation_exposes_agent_loop_contract_fields_for_errors() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="memory.search",
            input_schema={"required": ["query"], "properties": {"query": {"type": "string"}}},
        ),
        lambda args: {"matches": [args["query"]]},
    )

    observation = ToolExecutor(registry).execute(
        ToolCall(tool_name="memory.search", arguments={}, call_id="call-missing"),
        ToolPolicy(allowed_tools=["memory.search"]),
    )
    payload = observation.to_dict()

    assert payload["tool_call_id"] == "call-missing"
    assert payload["tool_name"] == "memory.search"
    assert payload["status"] == "failed"
    assert payload["artifact_ref"] is None
    assert payload["sample"] is None
    assert payload["error_type"] == "ToolRuntimeError"
    assert payload["result"]["error"] == {
        "type": "ToolRuntimeError",
        "message": "missing required arguments for memory.search: query",
    }
    assert payload["result"]["duration_ms"] >= 0
    assert payload["result"]["artifact_ref"] is None
    assert payload["result"]["metadata"] == {}
    assert payload["result"]["redaction_report"]["redacted"] is True


def test_tool_executor_allows_allowlisted_generic_fetch_tool() -> None:
    calls = {"count": 0}
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="http.fetch",
            input_schema={"required": [], "properties": {}, "additionalProperties": False},
        ),
        lambda args: calls.__setitem__("count", calls["count"] + 1),
    )

    observation = ToolExecutor(registry).execute(
        ToolCall(
            tool_name="http.fetch",
            arguments={},
            requested_by_agent_id="collector",
        ),
        ToolPolicy(allowed_tools=["http.fetch"]),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert calls["count"] == 1


def test_mcp_adapter_namespaces_tools_and_wraps_transport_errors() -> None:
    registry = ToolRegistry()
    adapter = MCPToolAdapter(_FailingMCPClient())
    server = MCPServerConfig(
        server_id="fixture-server",
        name="Fixture",
        transport="in_memory",
        timeout_seconds=1.0,
    )

    definitions = adapter.register_tools(registry, server)

    assert [definition.name for definition in definitions] == ["mcp.fixture_server.echo"]
    try:
        registry.get("mcp.fixture_server.echo").executor({"message": "hello"})
    except ToolRuntimeError as exc:
        assert "MCP transport error" in str(exc)
    else:
        raise AssertionError("MCP transport error should be wrapped")


def test_mcp_adapter_wraps_timeout() -> None:
    registry = ToolRegistry()
    adapter = MCPToolAdapter(_SlowMCPClient())
    server = MCPServerConfig(
        server_id="slow-server",
        name="Slow",
        transport="in_memory",
        timeout_seconds=0.01,
    )
    adapter.register_tools(registry, server)

    started = time.perf_counter()
    try:
        registry.get("mcp.slow_server.echo").executor({"message": "hello"})
    except ToolTimeoutError as exc:
        assert "MCP operation timed out" in str(exc)
    else:
        raise AssertionError("MCP timeout should be wrapped")

    assert time.perf_counter() - started < 0.1


def test_tool_test_runner_supports_contract_fields_and_dry_run() -> None:
    calls = {"count": 0}
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="memory.search",
            input_schema={
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 3},
                },
                "additionalProperties": False,
            },
        ),
        lambda args: calls.__setitem__("count", calls["count"] + 1)
        or {"matches": [args["query"]], "limit": args["limit"]},
    )

    report = ToolTestRunner(registry).run_case(
        ToolTestCase(
            name="memory search contract",
            tool_name="memory.search",
            args={"query": "chips"},
            policy=ToolPolicy(allowed_tools=["memory.search"]),
            expected_output_keys=["matches", "limit"],
        )
    )
    dry_report = ToolTestRunner(registry).run_case(
        ToolTestCase(
            name="memory search dry run",
            tool_name="memory.search",
            args={"query": "chips"},
            policy=ToolPolicy(allowed_tools=["memory.search"]),
            expected_output_keys=["dry_run", "tool_name"],
            dry_run=True,
        )
    )

    assert report.passed is True
    assert dry_report.passed is True
    assert calls["count"] == 1


def test_tool_test_runner_checks_error_type_redaction_and_approval() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="memory.secret",
            input_schema={"required": [], "properties": {}, "additionalProperties": False},
        ),
        lambda args: {"token": "hidden-token"},
    )
    registry.register(
        ToolDefinition(
            name="report.publish",
            side_effect="publishing",
            requires_approval=True,
            input_schema={"required": [], "properties": {}, "additionalProperties": False},
        ),
        lambda args: {"published": True},
    )

    runner = ToolTestRunner(registry)
    redaction_report = runner.run_case(
        ToolTestCase(
            name="redaction contract",
            tool_name="memory.secret",
            policy=ToolPolicy(allowed_tools=["memory.secret"]),
            require_redaction=True,
        )
    )
    approval_report = runner.run_case(
        ToolTestCase(
            name="approval contract",
            tool_name="report.publish",
            policy=ToolPolicy(allowed_tools=["report.publish"], allow_dangerous_tools=True),
            expected_status=ToolStatus.APPROVAL_REQUIRED,
            require_approval_required=True,
            dry_run=True,
        )
    )
    error_report = runner.run_case(
        ToolTestCase(
            name="validation contract",
            tool_name="memory.secret",
            args={"extra": True},
            policy=ToolPolicy(allowed_tools=["memory.secret"]),
            expected_status=ToolStatus.FAILED,
            expected_error_type="ToolRuntimeError",
            dry_run=True,
        )
    )

    assert redaction_report.passed is True
    assert redaction_report.observation.result.output["token"] == REDACTED_VALUE
    assert approval_report.passed is True
    assert error_report.passed is True


def test_tool_batch_executor_best_effort_and_strict_modes() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="memory.first",
            input_schema={"required": [], "properties": {}, "additionalProperties": False},
        ),
        lambda args: (_ for _ in ()).throw(RuntimeError("first failed")),
    )
    registry.register(
        ToolDefinition(
            name="memory.second",
            input_schema={"required": [], "properties": {}, "additionalProperties": False},
        ),
        lambda args: {"ok": True},
    )
    calls = [
        ToolCall(tool_name="memory.first", arguments={}),
        ToolCall(tool_name="memory.second", arguments={}),
    ]
    policy = ToolPolicy(allowed_tools=["memory.first", "memory.second"])
    executor = ToolBatchExecutor(registry)

    best_effort = executor.execute_batch(calls, policy, mode="best_effort")
    strict = executor.execute_batch(calls, policy, mode="strict")

    assert [observation.status for observation in best_effort] == [
        ToolStatus.FAILED,
        ToolStatus.SUCCEEDED,
    ]
    assert [observation.status for observation in strict] == [ToolStatus.FAILED]


class _FailingMCPClient:
    def list_tools(self, server: MCPServerConfig) -> list[dict[str, Any]]:
        return [{"name": "echo", "input_schema": {"required": []}}]

    def call_tool(
        self,
        server: MCPServerConfig,
        remote_tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        raise OSError("transport closed")


class _SlowMCPClient:
    def list_tools(self, server: MCPServerConfig) -> list[dict[str, Any]]:
        return [{"name": "echo", "input_schema": {"required": []}}]

    def call_tool(
        self,
        server: MCPServerConfig,
        remote_tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        time.sleep(0.2)
        return {"echo": arguments.get("message")}
