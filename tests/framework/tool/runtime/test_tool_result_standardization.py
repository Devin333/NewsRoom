from __future__ import annotations

import time

from framework.tool import ToolCall, ToolDefinition, ToolExecutor, ToolPolicy, ToolRegistry, ToolStatus


def test_tool_result_standard_fields_for_success_and_record() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="sample.echo", input_schema={"required": ["message"]}),
        lambda args: {"message": args["message"]},
    )

    executor = ToolExecutor(registry)
    observation = executor.execute(
        ToolCall(tool_name="sample.echo", arguments={"message": "hi"}, call_id="call-1"),
        ToolPolicy(allowed_tools=["sample.echo"]),
    )
    payload = observation.result.to_dict()
    record = executor.list_records()[0].to_dict()

    assert observation.status == ToolStatus.SUCCEEDED
    assert payload["redacted_output"] == {"message": "hi"}
    assert payload["policy_trace"]["allowed"] is True
    assert payload["gate_result"]["decision"] == "pass"
    assert payload["duration_ms"] is not None
    assert payload["retry_count"] == 0
    assert payload["timeout"] is False
    assert payload["error_envelope"] is None
    assert record["policy_trace"]["tool_name"] == "sample.echo"
    assert record["retry_count"] == 0
    assert record["timeout"] is False


def test_tool_result_standard_fields_for_block_approval_failure_and_timeout() -> None:
    registry = ToolRegistry()
    registry.register(ToolDefinition(name="sample.allowed", input_schema={}), lambda args: {"ok": True})
    registry.register(ToolDefinition(name="sample.approval", input_schema={}, requires_approval=True), lambda args: {"ok": True})
    registry.register(ToolDefinition(name="sample.fail", input_schema={}), lambda args: (_ for _ in ()).throw(RuntimeError("boom")))
    registry.register(
        ToolDefinition(name="sample.slow", input_schema={}, timeout_seconds=0.01),
        lambda args: time.sleep(0.05) or {"ok": True},
    )

    blocked = ToolExecutor(registry).execute(
        ToolCall(tool_name="sample.allowed", call_id="blocked"),
        ToolPolicy(allowed_tools=[]),
    ).result.to_dict()
    approval = ToolExecutor(registry).execute(
        ToolCall(tool_name="sample.approval", call_id="approval"),
        ToolPolicy(allowed_tools=["sample.approval"], require_approval_for_side_effects=True),
    ).result.to_dict()
    failed = ToolExecutor(registry).execute(
        ToolCall(tool_name="sample.fail", call_id="failed"),
        ToolPolicy(allowed_tools=["sample.fail"]),
    ).result.to_dict()
    timeout = ToolExecutor(registry).execute(
        ToolCall(tool_name="sample.slow", call_id="timeout"),
        ToolPolicy(allowed_tools=["sample.slow"]),
    ).result.to_dict()

    assert blocked["status"] == "blocked"
    assert blocked["policy_trace"]["allowed"] is False
    assert blocked["error_envelope"]["error_type"] == "ToolPermissionError"
    assert approval["status"] == "approval_required"
    assert approval["policy_trace"]["requires_approval"] is True
    assert approval["policy_trace"]["approval_granted"] is False
    assert failed["status"] == "failed"
    assert failed["error_envelope"]["error_type"] == "RuntimeError"
    assert timeout["status"] == "timeout"
    assert timeout["timeout"] is True
    assert timeout["error_envelope"]["error_type"] == "ToolTimeoutError"


def test_tool_retry_count_reports_actual_retries() -> None:
    attempts = {"count": 0}

    def flaky(args):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("try again")
        return {"ok": True}

    registry = ToolRegistry()
    registry.register(ToolDefinition(name="sample.flaky", input_schema={}, max_attempts=3), flaky)

    observation = ToolExecutor(registry).execute(
        ToolCall(tool_name="sample.flaky", call_id="flaky"),
        ToolPolicy(allowed_tools=["sample.flaky"]),
    )
    payload = observation.result.to_dict()
    retry_check = [
        check
        for check in payload["policy_trace"]["checks"]
        if check["check_id"] == "tool.retry"
    ][0]

    assert observation.status == ToolStatus.SUCCEEDED
    assert attempts["count"] == 3
    assert payload["retry_count"] == 2
    assert retry_check["metadata"]["attempts"] == 3
    assert retry_check["metadata"]["retry_count"] == 2


def test_tool_retry_count_zero_when_first_attempt_succeeds() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="sample.first", input_schema={}, max_attempts=3),
        lambda args: {"ok": True},
    )

    result = ToolExecutor(registry).execute(
        ToolCall(tool_name="sample.first", call_id="first"),
        ToolPolicy(allowed_tools=["sample.first"]),
    ).result

    assert result.retry_count == 0
