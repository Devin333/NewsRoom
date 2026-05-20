from __future__ import annotations

from framework.tool import ToolCall, ToolDefinition, ToolExecutor, ToolPolicy, ToolRegistry, ToolStatus


def test_policy_trace_records_allowlist_dangerous_approval_and_output_checks() -> None:
    registry = ToolRegistry()
    registry.register(ToolDefinition(name="sample.ok", input_schema={}), lambda args: {"ok": True})
    registry.register(
        ToolDefinition(name="dangerous.delete", input_schema={}, is_dangerous=True),
        lambda args: {"ok": True},
    )
    registry.register(
        ToolDefinition(name="sample.publish", input_schema={}, requires_approval=True),
        lambda args: {"ok": True},
    )
    registry.register(
        ToolDefinition(name="sample.large", input_schema={}, max_result_bytes=4),
        lambda args: {"message": "too large"},
    )

    allowed = ToolExecutor(registry).execute(
        ToolCall(tool_name="sample.ok", call_id="allowed"),
        ToolPolicy(allowed_tools=["sample.ok"]),
    )
    denied = ToolExecutor(registry).execute(
        ToolCall(tool_name="sample.ok", call_id="denied"),
        ToolPolicy(allowed_tools=[]),
    )
    dangerous = ToolExecutor(registry).execute(
        ToolCall(tool_name="dangerous.delete", call_id="dangerous"),
        ToolPolicy(allowed_tools=["dangerous.delete"], allow_dangerous_tools=False),
    )
    approval = ToolExecutor(registry).execute(
        ToolCall(tool_name="sample.publish", call_id="approval"),
        ToolPolicy(allowed_tools=["sample.publish"], require_approval_for_side_effects=True),
    )
    oversized = ToolExecutor(registry).execute(
        ToolCall(tool_name="sample.large", call_id="large"),
        ToolPolicy(allowed_tools=["sample.large"]),
    )

    assert allowed.status == ToolStatus.SUCCEEDED
    assert _check_ids(allowed) >= {"tool.resolve", "tool.permission", "tool.output_size"}
    assert denied.result.policy_trace.allowed is False
    assert "tool.permission" in _check_ids(denied)
    assert dangerous.status == ToolStatus.BLOCKED
    assert "tool.risk" in _failed_check_ids(dangerous)
    assert approval.status == ToolStatus.APPROVAL_REQUIRED
    assert "tool.approval" in _failed_check_ids(approval)
    assert oversized.status == ToolStatus.FAILED
    assert "tool.output_size" in _failed_check_ids(oversized)


def _check_ids(observation) -> set[str]:
    return {
        str(check["check_id"])
        for check in observation.result.policy_trace.to_dict()["checks"]
    }


def _failed_check_ids(observation) -> set[str]:
    return {
        str(check["check_id"])
        for check in observation.result.policy_trace.to_dict()["checks"]
        if not check["passed"]
    }
