from __future__ import annotations

import time

from framework.tool import ToolCall, ToolDefinition, ToolExecutor, ToolPolicy, ToolRegistry, ToolStatus
from framework.artifacts import ArtifactManager


def test_tool_runtime_contract_standard_result_paths(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="contract.echo", input_schema={"required": ["message"]}),
        lambda args: {"message": args["message"], "token": "sk-1234567890abcdef"},
    )
    registry.register(
        ToolDefinition(name="contract.large", input_schema={}),
        lambda args: {"text": "x" * 128},
    )
    registry.register(
        ToolDefinition(name="contract.slow", input_schema={}, timeout_seconds=0.01),
        lambda args: time.sleep(0.05) or {"ok": True},
    )

    success = ToolExecutor(registry).execute(
        ToolCall(tool_name="contract.echo", arguments={"message": "hi"}, call_id="call-ok"),
        ToolPolicy(allowed_tools=["contract.echo"]),
    )
    denied = ToolExecutor(registry).execute(
        ToolCall(tool_name="contract.echo", arguments={"message": "hi"}, call_id="call-denied"),
        ToolPolicy(allowed_tools=[]),
    )
    spilled = ToolExecutor(
        registry,
        artifact_manager=ArtifactManager(tmp_path),
        run_id="run-tool-contract",
    ).execute(
        ToolCall(tool_name="contract.large", call_id="call-large"),
        ToolPolicy(allowed_tools=["contract.large"], spill_large_results_to_artifact=True, max_result_chars_inline=8),
    )
    timeout = ToolExecutor(registry).execute(
        ToolCall(tool_name="contract.slow", call_id="call-timeout"),
        ToolPolicy(allowed_tools=["contract.slow"]),
    )

    assert success.status == ToolStatus.SUCCEEDED
    assert success.result.policy_trace.allowed is True
    assert "sk-1234567890abcdef" not in str(success.result.to_dict()["redacted_output"])
    assert denied.status == ToolStatus.BLOCKED
    assert denied.result.gate_result["decision"] == "block"
    assert spilled.status == ToolStatus.SUCCEEDED
    assert spilled.result.artifact_refs
    assert spilled.result.policy_trace.checks[-1]["check_id"] == "tool.artifact_spill"
    assert timeout.status == ToolStatus.TIMEOUT
    assert timeout.result.timeout is True
    assert timeout.result.error_envelope["error_type"] == "ToolTimeoutError"
