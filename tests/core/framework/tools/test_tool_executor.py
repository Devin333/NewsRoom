import json
import time
from hashlib import sha256

from core.framework.artifacts import ArtifactManager
from core.framework.workers import InMemoryApprovalStore
from framework.tool import (
    REDACTED_VALUE,
    ToolCall,
    ToolDefinition,
    ToolExecutor,
    ToolPolicy,
    ToolRegistry,
    ToolResult,
    ToolStatus,
)
from framework.tool.governance.redaction import contains_redacted_value, redact_sensitive_values


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="memory.search",
            description="Search local memory",
            input_schema={"required": ["query"]},
        ),
        lambda args: {"matches": [{"title": args["query"], "score": 1.0}]},
    )
    return registry


def test_tool_executor_runs_allowed_tool_and_returns_observation() -> None:
    executor = ToolExecutor(_registry())

    observation = executor.execute(
        ToolCall(
            tool_name="memory.search",
            arguments={"query": "chip exports"},
            requested_by_agent_id="analyst",
            call_id="call-1",
        ),
        ToolPolicy(allowed_tools=["memory.search"]),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.call.call_id == "call-1"
    assert observation.result.output["matches"][0]["title"] == "chip exports"
    assert observation.elapsed_ms >= 0
    payload = observation.to_dict()
    assert payload["tool_call_id"] == "call-1"
    assert payload["tool_name"] == "memory.search"
    assert payload["status"] == "succeeded"
    assert payload["summary"] == "Tool memory.search succeeded"
    assert payload["highlights"] == ["matches: 1 item(s)"]
    assert payload["artifact_refs"] == []
    assert payload["safe_for_llm"] is True
    assert payload["call"]["call_id"] == "call-1"
    assert payload["result"]["status"] == "succeeded"
    assert [event.event_type for event in executor.list_events()] == [
        "tool_call_requested",
        "tool_args_validated",
        "tool_started",
        "tool_succeeded",
        "tool_observation_created",
    ]
    assert executor.metrics.to_dict()["succeeded_calls"] == 1
    assert executor.metrics.to_dict()["calls_by_tool"] == {"memory.search": 1}
    record = executor.list_records()[0]
    assert record.tool_call.call_id == "call-1"
    assert record.tool_result.status == ToolStatus.SUCCEEDED
    assert record.validation_passed is True
    assert record.guardrails_passed is True
    assert record.approval_required is False
    assert record.to_dict()["events"] == [
        "tool_call_requested",
        "tool_args_validated",
        "tool_started",
        "tool_succeeded",
        "tool_observation_created",
    ]


def test_tool_executor_blocks_disallowed_tool() -> None:
    executor = ToolExecutor(_registry())

    observation = executor.execute(
        ToolCall(
            tool_name="memory.search",
            arguments={"query": "chip exports"},
            requested_by_agent_id="writer",
        ),
        ToolPolicy(allowed_tools=[]),
    )

    assert observation.status == ToolStatus.BLOCKED
    assert observation.result.error_type == "ToolPermissionError"


def test_tool_executor_blocks_dangerous_tool_by_default() -> None:
    calls = {"count": 0}
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="system.command",
            is_dangerous=True,
            input_schema={"required": ["command"], "properties": {"command": {"type": "string"}}},
        ),
        lambda args: calls.__setitem__("count", calls["count"] + 1),
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(tool_name="system.command", arguments={"command": "echo hello"}),
        ToolPolicy(allowed_tools=["system.command"]),
    )

    assert observation.status == ToolStatus.BLOCKED
    assert calls["count"] == 0
    assert observation.result.error_type == "ToolPermissionError"
    assert "dangerous tool is not allowed" in (observation.result.error_message or "")


def test_tool_executor_blocks_mcp_tool_by_default_even_when_allowlisted() -> None:
    calls = {"count": 0}
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="mcp.fixture.echo", input_schema={"required": ["message"]}),
        lambda args: calls.__setitem__("count", calls["count"] + 1),
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(tool_name="mcp.fixture.echo", arguments={"message": "hello"}),
        ToolPolicy(allowed_tools=["mcp.fixture.echo"]),
    )

    assert observation.status == ToolStatus.BLOCKED
    assert observation.result.error_type == "ToolPermissionError"
    assert calls["count"] == 0


def test_tool_executor_runs_mcp_tool_when_policy_explicitly_allows_mcp() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="mcp.fixture.echo", input_schema={"required": ["message"]}),
        lambda args: {"echo": args["message"]},
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(tool_name="mcp.fixture.echo", arguments={"message": "hello"}),
        ToolPolicy(allowed_tools=["mcp.fixture.echo"], allow_mcp_tools=True),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output == {"echo": "hello"}


def test_tool_executor_requires_approval_for_side_effecting_tool() -> None:
    calls = {"count": 0}
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="report.publish",
            side_effect="publishing",
            input_schema={"required": ["report_id"], "properties": {"report_id": {"type": "string"}}},
        ),
        lambda args: calls.__setitem__("count", calls["count"] + 1),
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(tool_name="report.publish", arguments={"report_id": "report-1"}),
        ToolPolicy(allowed_tools=["report.publish"], allow_dangerous_tools=True),
    )

    assert observation.status == ToolStatus.APPROVAL_REQUIRED
    assert calls["count"] == 0
    assert observation.result.approval_id is None
    assert "requires approval" in (observation.result.output_summary or "")


def test_tool_executor_stores_tool_approval_request_when_store_is_configured() -> None:
    calls = {"count": 0}
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="report.publish",
            side_effect="publishing",
            input_schema={
                "required": ["report_id"],
                "properties": {
                    "report_id": {"type": "string"},
                    "authorization": {"type": "string"},
                },
            },
        ),
        lambda args: calls.__setitem__("count", calls["count"] + 1),
    )
    approval_store = InMemoryApprovalStore()
    executor = ToolExecutor(registry, run_id="run-approval", approval_store=approval_store)

    observation = executor.execute(
        ToolCall(
            tool_name="report.publish",
            arguments={"report_id": "report-1", "authorization": "Bearer secret12345"},
            requested_by_agent_id="publisher",
            call_id="call-approval",
        ),
        ToolPolicy(allowed_tools=["report.publish"], allow_dangerous_tools=True),
    )

    approvals = approval_store.list_approvals()
    approval = approvals[0]
    tool_approval = approval.payload["tool_approval"]

    assert observation.status == ToolStatus.APPROVAL_REQUIRED
    assert calls["count"] == 0
    assert len(approvals) == 1
    assert observation.result.approval_id == approval.approval_id
    assert approval.requested_action == "tool:report.publish"
    assert approval.risk_level == "high"
    assert approval.task_id == "call-approval"
    assert approval.run_id == "run-approval"
    assert approval.requested_by == "publisher"
    assert approval.metadata["approval_type"] == "tool_execution"
    assert tool_approval["tool_call"]["arguments"]["authorization"] == REDACTED_VALUE
    record = executor.list_records()[0]
    assert record.approval_required is True
    assert record.approval_id == approval.approval_id
    assert record.validation_passed is True
    assert "tool_approval_required" in record.events


def test_tool_executor_validates_arguments_before_creating_tool_approval() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="report.publish",
            side_effect="publishing",
            input_schema={
                "required": ["report_id"],
                "properties": {"report_id": {"type": "string"}},
            },
        ),
        lambda args: {"published": args["report_id"]},
    )
    approval_store = InMemoryApprovalStore()
    executor = ToolExecutor(registry, approval_store=approval_store)

    observation = executor.execute(
        ToolCall(tool_name="report.publish", arguments={}),
        ToolPolicy(allowed_tools=["report.publish"], allow_dangerous_tools=True),
    )

    assert observation.status == ToolStatus.FAILED
    assert approval_store.list_approvals() == []


def test_tool_executor_can_run_side_effecting_tool_when_approval_gate_is_disabled() -> None:
    calls = {"count": 0}
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="notification.internal_send",
            side_effect="external_write",
            input_schema={"required": ["message"], "properties": {"message": {"type": "string"}}},
        ),
        lambda args: calls.__setitem__("count", calls["count"] + 1) or {"sent": args["message"]},
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(tool_name="notification.internal_send", arguments={"message": "ready"}),
        ToolPolicy(
            allowed_tools=["notification.internal_send"],
            allow_dangerous_tools=True,
            require_approval_for_side_effects=False,
        ),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert calls["count"] == 1
    assert observation.result.output == {"sent": "ready"}


def test_tool_executor_returns_timeout_for_slow_tool() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="source.slow",
            input_schema={"required": ["url"]},
            timeout_seconds=0.02,
        ),
        lambda args: time.sleep(0.2) or {"url": args["url"]},
    )
    executor = ToolExecutor(registry)

    started_at = time.perf_counter()
    observation = executor.execute(
        ToolCall(tool_name="source.slow", arguments={"url": "https://example.com"}),
        ToolPolicy(allowed_tools=["source.slow"]),
    )
    elapsed = time.perf_counter() - started_at

    assert observation.status == ToolStatus.TIMEOUT
    assert observation.result.error_type == "ToolTimeoutError"
    assert "exceeded timeout" in (observation.result.error_message or "")
    assert elapsed < 0.15


def test_tool_executor_uses_policy_default_timeout_for_fast_tool() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="memory.fast", input_schema={"required": ["query"]}),
        lambda args: {"query": args["query"]},
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(tool_name="memory.fast", arguments={"query": "chips"}),
        ToolPolicy(allowed_tools=["memory.fast"], timeout_seconds_default=0.5),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output == {"query": "chips"}


def test_tool_executor_retries_transient_invocation_failure() -> None:
    calls = {"count": 0}

    def flaky_tool(args: dict) -> dict:
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary connector failure")
        return {"query": args["query"], "attempt": calls["count"]}

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="memory.flaky", input_schema={"required": ["query"]}),
        flaky_tool,
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(tool_name="memory.flaky", arguments={"query": "chips"}),
        ToolPolicy(allowed_tools=["memory.flaky"], max_attempts_default=2),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert calls["count"] == 2
    assert observation.result.output == {"query": "chips", "attempt": 2}


def test_tool_executor_does_not_retry_by_default() -> None:
    calls = {"count": 0}

    def failing_tool(args: dict) -> dict:
        calls["count"] += 1
        raise RuntimeError("permanent failure")

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="memory.failing", input_schema={"required": ["query"]}),
        failing_tool,
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(tool_name="memory.failing", arguments={"query": "chips"}),
        ToolPolicy(allowed_tools=["memory.failing"]),
    )

    assert observation.status == ToolStatus.FAILED
    assert calls["count"] == 1
    assert observation.result.error_type == "RuntimeError"


def test_tool_executor_uses_tool_specific_max_attempts() -> None:
    calls = {"count": 0}

    def flaky_tool(args: dict) -> dict:
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary connector failure")
        return {"ok": True}

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="source.flaky",
            input_schema={"required": ["url"]},
            max_attempts=2,
        ),
        flaky_tool,
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(tool_name="source.flaky", arguments={"url": "https://example.com"}),
        ToolPolicy(allowed_tools=["source.flaky"], max_attempts_default=1),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert calls["count"] == 2
    assert observation.result.output == {"ok": True}


def test_tool_executor_fails_missing_required_arguments() -> None:
    executor = ToolExecutor(_registry())

    observation = executor.execute(
        ToolCall(tool_name="memory.search", arguments={}, requested_by_agent_id="analyst"),
        ToolPolicy(allowed_tools=["memory.search"]),
    )

    assert observation.status == ToolStatus.FAILED
    assert observation.result.error_type == "ToolRuntimeError"
    assert "missing required arguments" in (observation.result.error_message or "")
    metrics = executor.metrics.to_dict()
    assert metrics["failed_calls"] == 1
    assert metrics["failures_by_error_type"] == {"ToolRuntimeError": 1}
    assert [event.event_type for event in executor.list_events()] == [
        "tool_call_requested",
        "tool_failed",
        "tool_observation_created",
    ]


def test_tool_executor_rejects_invalid_argument_type_before_invocation() -> None:
    calls = {"count": 0}
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="source.fetch",
            input_schema={
                "required": ["url"],
                "properties": {"url": {"type": "string"}},
            },
        ),
        lambda args: calls.__setitem__("count", calls["count"] + 1),
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(tool_name="source.fetch", arguments={"url": 123}),
        ToolPolicy(allowed_tools=["source.fetch"]),
    )

    assert observation.status == ToolStatus.FAILED
    assert calls["count"] == 0
    assert observation.result.error_type == "ToolRuntimeError"
    assert "must be string" in (observation.result.error_message or "")


def test_tool_executor_rejects_unexpected_argument_when_schema_is_closed() -> None:
    calls = {"count": 0}
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="artifact.load",
            input_schema={
                "required": ["artifact_key"],
                "properties": {"artifact_key": {"type": "string"}},
                "additionalProperties": False,
            },
        ),
        lambda args: calls.__setitem__("count", calls["count"] + 1),
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="artifact.load",
            arguments={"artifact_key": "output", "extra": "not allowed"},
        ),
        ToolPolicy(allowed_tools=["artifact.load"]),
    )

    assert observation.status == ToolStatus.FAILED
    assert calls["count"] == 0
    assert "unexpected arguments" in (observation.result.error_message or "")


def test_tool_executor_rejects_enum_violation_before_invocation() -> None:
    calls = {"count": 0}
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="report.render",
            input_schema={
                "required": ["format"],
                "properties": {"format": {"type": "string", "enum": ["markdown", "json"]}},
            },
        ),
        lambda args: calls.__setitem__("count", calls["count"] + 1),
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(tool_name="report.render", arguments={"format": "pdf"}),
        ToolPolicy(allowed_tools=["report.render"]),
    )

    assert observation.status == ToolStatus.FAILED
    assert calls["count"] == 0
    assert "must be one of" in (observation.result.error_message or "")


def test_tool_executor_runs_schema_valid_arguments() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="source.limit",
            input_schema={
                "required": ["limit", "include_archived"],
                "properties": {
                    "limit": {"type": "integer"},
                    "include_archived": {"type": "boolean"},
                    "topics": {"type": ["array", "null"]},
                },
                "additionalProperties": False,
            },
        ),
        lambda args: {"accepted": args},
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="source.limit",
            arguments={"limit": 2, "include_archived": False, "topics": None},
        ),
        ToolPolicy(allowed_tools=["source.limit"]),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["accepted"]["limit"] == 2


def test_tool_executor_redacts_sensitive_output_and_serialized_arguments() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="http.safe_fetch",
            description="Fetch a protected resource",
            input_schema={"required": ["url"]},
        ),
        lambda args: {
            "token": "hidden-token",
            "nested": {"api_key": "hidden-key", "safe": "visible"},
            "headers": ["Bearer abcdef1234567890"],
            "url": args["url"],
        },
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="http.safe_fetch",
            arguments={"url": "https://example.com", "authorization": "Bearer input-secret"},
            requested_by_agent_id="analyst",
            call_id="call-1",
        ),
        ToolPolicy(allowed_tools=["http.safe_fetch"]),
    )

    payload = observation.to_dict()

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["token"] == REDACTED_VALUE
    assert observation.result.output["nested"]["api_key"] == REDACTED_VALUE
    assert observation.result.output["nested"]["safe"] == "visible"
    assert payload["call"]["arguments"]["authorization"] == REDACTED_VALUE
    assert payload["result"]["redacted"] is True
    assert "hidden-token" not in str(payload)
    assert "hidden-key" not in str(payload)
    assert "input-secret" not in str(payload)
    redaction_events = [
        event for event in executor.list_events() if event.event_type == "tool_result_redacted"
    ]
    assert len(redaction_events) == 1
    assert redaction_events[0].payload == {"redacted": True}
    assert "hidden-token" not in str(redaction_events[0].to_dict())


def test_tool_result_to_dict_redacts_secret_like_strings() -> None:
    fake_secret = "sk" + "-abcdef1234567890"
    result = ToolResult(
        status=ToolStatus.SUCCEEDED,
        output={"message": f"provider returned {fake_secret}"},
    )

    payload = result.to_dict()

    assert payload["output"]["message"] == f"provider returned {REDACTED_VALUE}"


def test_tool_redactor_handles_nested_lists() -> None:
    payload = redact_sensitive_values(
        [{"password": "hidden"}, {"message": "Bearer abcdef1234567890"}]
    )

    assert payload == [
        {"password": REDACTED_VALUE},
        {"message": REDACTED_VALUE},
    ]
    assert contains_redacted_value(payload) is True


def test_tool_executor_spills_large_redacted_result_to_artifact(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="memory.large", input_schema={"required": ["query"]}),
        lambda args: {
            "items": [{"title": args["query"], "body": "x" * 80}],
            "token": "hidden-token",
        },
    )
    artifact_manager = ArtifactManager(tmp_path)
    artifact_manager.start_run("run-1")
    executor = ToolExecutor(
        registry,
        artifact_manager=artifact_manager,
        run_id="run-1",
    )

    observation = executor.execute(
        ToolCall(
            tool_name="memory.large",
            arguments={"query": "chips"},
            requested_by_agent_id="analyst",
            call_id="call-large",
        ),
        ToolPolicy(allowed_tools=["memory.large"], max_result_chars_inline=20),
    )

    payload = observation.to_dict()
    artifact_ref = payload["result"]["artifact_refs"][0]
    artifact_path = tmp_path / "run-1" / artifact_ref["relative_path"]
    artifact_payload = json.loads(artifact_path.read_text(encoding="utf-8"))

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output is None
    assert observation.result.output_bytes is not None
    assert observation.result.output_bytes > 20
    assert "Tool result spilled" in (observation.result.output_summary or "")
    assert artifact_ref["artifact_id"] == "tool_result:call-large"
    assert artifact_ref["content_type"] == "application/json"
    assert artifact_path.exists()
    assert artifact_ref["checksum"] == sha256(artifact_path.read_bytes()).hexdigest()
    assert payload["summary"] == "Tool result spilled to artifact: tool_results/call-large.json"
    assert payload["artifact_refs"] == [artifact_ref]
    assert payload["highlights"] == []
    assert artifact_payload["call"]["call_id"] == "call-large"
    assert artifact_payload["output"]["token"] == REDACTED_VALUE
    assert "hidden-token" not in artifact_path.read_text(encoding="utf-8")
    assert "tool_result_spilled" in [event.event_type for event in executor.list_events()]
    assert "tool_output_guardrail_failed" not in [
        event.event_type for event in executor.list_events()
    ]
    assert executor.metrics.to_dict()["spilled_result_count"] == 1


def test_tool_executor_fails_output_that_exceeds_tool_max_result_bytes() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="memory.large",
            input_schema={"required": ["query"]},
            max_result_bytes=20,
        ),
        lambda args: {"items": [{"title": args["query"], "body": "x" * 80}]},
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(tool_name="memory.large", arguments={"query": "chips"}),
        ToolPolicy(allowed_tools=["memory.large"]),
    )

    guardrail_events = [
        event
        for event in executor.list_events()
        if event.event_type == "tool_output_guardrail_failed"
    ]
    assert observation.status == ToolStatus.FAILED
    assert observation.result.error_type == "ToolRuntimeError"
    assert "max_result_bytes" in (observation.result.error_message or "")
    assert observation.result.output is None
    assert observation.result.output_bytes is not None
    assert observation.result.output_bytes > 20
    assert len(guardrail_events) == 1
    assert guardrail_events[0].payload["reason"] == "max_result_bytes_exceeded"
    assert guardrail_events[0].payload["max_result_bytes"] == 20
    assert "x" * 20 not in str(guardrail_events[0].to_dict())


def test_tool_executor_requires_artifact_context_for_large_result_pointer() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="memory.large", input_schema={"required": ["query"]}),
        lambda args: {"items": ["x" * 80], "token": "hidden-token"},
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(tool_name="memory.large", arguments={"query": "chips"}),
        ToolPolicy(allowed_tools=["memory.large"], max_result_chars_inline=20),
    )

    assert observation.status == ToolStatus.FAILED
    assert observation.result.error_type == "ToolRuntimeError"
    assert "artifact context" in (observation.result.error_message or "")
    assert observation.result.output is None
    assert observation.result.artifact_refs == []
    assert observation.result.output_bytes is not None
    assert observation.result.output_bytes > 20
