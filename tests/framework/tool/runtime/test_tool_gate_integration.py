from __future__ import annotations

from framework.tool import ToolCall, ToolDefinition, ToolExecutor, ToolPolicy, ToolRegistry, ToolStatus


def test_dangerous_tool_block_includes_gate_result() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="dangerous.delete", input_schema={}, is_dangerous=True),
        lambda args: {"ok": True},
    )

    observation = ToolExecutor(registry).execute(
        ToolCall(tool_name="dangerous.delete", call_id="call-1"),
        ToolPolicy(allowed_tools=["dangerous.delete"], allow_dangerous_tools=False),
    )

    assert observation.status == ToolStatus.BLOCKED
    assert observation.result.gate_result["decision"] == "block"
    assert observation.result.gate_result["failed_dimensions"] == ["safety"]


def test_tool_approval_required_includes_warn_gate_result() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="sample.publish", input_schema={}, requires_approval=True),
        lambda args: {"ok": True},
    )

    observation = ToolExecutor(registry).execute(
        ToolCall(tool_name="sample.publish", call_id="call-2"),
        ToolPolicy(
            allowed_tools=["sample.publish"],
            require_approval_for_side_effects=True,
        ),
    )

    assert observation.status == ToolStatus.APPROVAL_REQUIRED
    assert observation.result.gate_result["decision"] == "warn"


def test_tool_output_size_gate_result_preserves_failed_status() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="sample.large", input_schema={}, max_result_bytes=4),
        lambda args: {"message": "too large"},
    )

    observation = ToolExecutor(registry).execute(
        ToolCall(tool_name="sample.large", call_id="call-3"),
        ToolPolicy(allowed_tools=["sample.large"]),
    )

    assert observation.status == ToolStatus.FAILED
    assert observation.result.gate_result["decision"] == "block"
    assert "resource" in observation.result.gate_result["failed_dimensions"]
