from core.framework.tools import (
    ToolCall,
    ToolDefinition,
    ToolExecutor,
    ToolPolicy,
    ToolRegistry,
    ToolStatus,
    build_builtin_tool_registry,
    classify_tool_risk,
    inspect_tool_executor,
    inspect_tool_policy,
    inspect_tool_registry,
    inspect_tool_runtime,
)


def _inspection_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="memory.search",
            input_schema={"required": ["query"], "properties": {"query": {"type": "string"}}},
            timeout_seconds=5,
            concurrency_safe=True,
        ),
        lambda args: {"matches": [{"title": args["query"]}]},
    )
    registry.register(
        ToolDefinition(
            name="report.publish",
            side_effect="publishing",
            requires_approval=True,
            input_schema={"required": ["report_id"], "properties": {"report_id": {"type": "string"}}},
            timeout_seconds=10,
        ),
        lambda args: {"published": True, "report_id": args["report_id"]},
    )
    registry.register(
        ToolDefinition(
            name="system.command",
            is_dangerous=True,
            side_effect="destructive",
            input_schema={"required": ["command"], "properties": {"command": {"type": "string"}}},
        ),
        lambda args: {"ran": args["command"]},
    )
    registry.register(
        ToolDefinition(
            name="mcp.fixture.echo",
            input_schema={"required": ["message"], "properties": {"message": {"type": "string"}}},
            timeout_seconds=3,
        ),
        lambda args: {"message": args["message"]},
    )
    return registry


def test_classify_tool_risk_is_deterministic() -> None:
    assert classify_tool_risk(ToolDefinition(name="memory.search")) == "low"
    assert (
        classify_tool_risk(
            ToolDefinition(name="local.write", side_effect="writes_local_state")
        )
        == "medium"
    )
    assert (
        classify_tool_risk(
            ToolDefinition(
                name="report.publish",
                side_effect="publishing",
                requires_approval=True,
            )
        )
        == "high"
    )
    assert (
        classify_tool_risk(
            ToolDefinition(
                name="system.command",
                side_effect="destructive",
                is_dangerous=True,
            )
        )
        == "critical"
    )


def test_inspect_tool_policy_reports_exposure_and_unknown_tools() -> None:
    registry = _inspection_registry()
    policy = ToolPolicy(
        allowed_tools=[
            "memory.search",
            "report.publish",
            "mcp.fixture.echo",
            "unknown.tool",
        ],
        blocked_tools=["unknown.blocked"],
        allow_mcp_tools=True,
    )

    inspection = inspect_tool_policy(registry, policy, agent_id="analyst")
    payload = inspection.to_dict()

    assert inspection.exposed_tool_count == 3
    assert inspection.unknown_allowed_tools == ["unknown.tool"]
    assert inspection.unknown_blocked_tools == ["unknown.blocked"]
    assert inspection.exposed_side_effect_tools == ["report.publish"]
    assert inspection.exposed_mcp_tools == ["mcp.fixture.echo"]
    assert payload["agent_id"] == "analyst"
    assert payload["broad_access"] is False


def test_inspect_tool_registry_reports_risk_namespaces_and_findings() -> None:
    registry = _inspection_registry()
    policy = ToolPolicy(
        allowed_tools=["memory.search", "report.publish", "system.command"],
        allow_dangerous_tools=True,
    )

    inspection = inspect_tool_registry(
        registry,
        policy=policy,
        agent_id="writer",
        agent_tool_policies={
            "writer": ToolPolicy(allowed_tools=["source.fetch_url", "report.publish"])
        },
    )
    payload = inspection.to_dict()
    finding_codes = {finding.code for finding in inspection.findings}
    namespaces = {namespace.namespace: namespace for namespace in inspection.namespaces}

    assert inspection.tool_count == 4
    assert inspection.namespace_count == 4
    assert inspection.registry_valid is True
    assert inspection.risk_summary.risk_counts == {
        "low": 2,
        "medium": 0,
        "high": 1,
        "critical": 1,
    }
    assert namespaces["report"].side_effect_count == 1
    assert namespaces["system"].dangerous_count == 1
    assert "dangerous_tool_defined" in finding_codes
    assert "policy_exposes_dangerous_tool" in finding_codes
    assert "agent_tool_boundary_violation" in finding_codes
    assert inspection.blocking_finding_count >= 2
    assert inspection.ok is False
    assert payload["risk_summary"]["dangerous_tools"] == 1
    assert payload["boundary_report"]["blocking_finding_count"] == 1


def test_inspect_tool_executor_summarizes_success_failed_and_blocked_calls() -> None:
    registry = _inspection_registry()
    executor = ToolExecutor(registry)
    policy = ToolPolicy(allowed_tools=["memory.search"])

    success = executor.execute(
        ToolCall(tool_name="memory.search", arguments={"query": "chips"}, call_id="ok"),
        policy,
    )
    blocked = executor.execute(
        ToolCall(tool_name="report.publish", arguments={"report_id": "r1"}, call_id="blocked"),
        policy,
    )
    failed = executor.execute(
        ToolCall(tool_name="memory.search", arguments={}, call_id="failed"),
        policy,
    )

    inspection = inspect_tool_executor(executor, recent_limit=2)
    payload = inspection.to_dict()

    assert success.status == ToolStatus.SUCCEEDED
    assert blocked.status == ToolStatus.BLOCKED
    assert failed.status == ToolStatus.FAILED
    assert inspection.total_records == 3
    assert inspection.status_counts["succeeded"] == 1
    assert inspection.status_counts["blocked"] == 1
    assert inspection.status_counts["failed"] == 1
    assert inspection.event_type_counts["tool_call_requested"] == 3
    assert inspection.event_type_counts["tool_observation_created"] == 3
    assert inspection.metrics.total_calls == 3
    assert inspection.failed_or_blocked_count == 2
    assert len(inspection.recent_records) == 2
    assert len(inspection.recent_events) == 2
    assert payload["metrics"]["calls_by_tool"] == {"memory.search": 2, "report.publish": 1}


def test_inspect_tool_runtime_combines_registry_and_executor() -> None:
    registry = _inspection_registry()
    executor = ToolExecutor(registry)
    executor.execute(
        ToolCall(tool_name="memory.search", arguments={"query": "chips"}, call_id="ok"),
        ToolPolicy(allowed_tools=["memory.search"]),
    )

    report = inspect_tool_runtime(
        registry,
        policy=ToolPolicy(allowed_tools=["memory.search"]),
        executor=executor,
        agent_id="analyst",
    )
    payload = report.to_dict()

    assert report.ok is True
    assert payload["summary"]["tool_count"] == 4
    assert payload["summary"]["executor_total_records"] == 1
    assert payload["summary"]["executor_status_counts"]["succeeded"] == 1
    assert payload["registry"]["policy"]["exposed_tool_count"] == 1
    assert payload["executor"]["total_records"] == 1


def test_builtin_registry_inspection_stays_offline_and_marks_network_tools_optional() -> None:
    registry = build_builtin_tool_registry(include_network_tools=False)
    inspection = inspect_tool_registry(registry)
    names = {tool.name for tool in inspection.tools}

    assert "source.parse_rss" in names
    assert "report.validate" in names
    assert "quality.duplicate_check" in names
    assert "control.set_output" in names
    assert "web.search" not in names
    assert "github.search_repositories" not in names
    assert inspection.registry_valid is True
    assert inspection.namespace_count >= 4
    assert inspection.risk_summary.side_effect_tools == 0
    assert inspection.risk_summary.tools_without_timeout >= 1
