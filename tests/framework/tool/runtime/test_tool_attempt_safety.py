from __future__ import annotations

import threading

import pytest

from framework.shared.attempts import current_attempt_context
from framework.tool import (
    MCPServerConfig,
    MCPToolAdapter,
    ToolCall,
    ToolDefinition,
    ToolExecutor,
    ToolPolicy,
    ToolRegistry,
    ToolSideEffect,
    ToolStatus,
    ToolTimeoutError,
)


def test_unconfirmed_tool_timeout_never_overlaps_retry_or_duplicates_late_effect() -> None:
    release = threading.Event()
    started = threading.Event()
    finished = threading.Event()
    lock = threading.Lock()
    calls = 0
    active = 0
    max_active = 0
    effects: list[str] = []

    def execute(_arguments: dict[str, object]) -> dict[str, bool]:
        nonlocal calls, active, max_active
        with lock:
            calls += 1
            active += 1
            max_active = max(max_active, active)
        started.set()
        release.wait(1)
        effects.append("published")
        with lock:
            active -= 1
        finished.set()
        return {"ok": True}

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="sample.unconfirmed",
            side_effect=ToolSideEffect.READ_ONLY,
            timeout_seconds=0.01,
            max_attempts=3,
        ),
        execute,
    )

    observation = ToolExecutor(registry).execute(
        ToolCall(tool_name="sample.unconfirmed", call_id="logical-call"),
        ToolPolicy(
            require_explicit_allowlist=False,
            require_approval_for_side_effects=False,
            cancellation_grace_seconds=0.005,
        ),
    )

    assert started.is_set()
    assert observation.status == ToolStatus.TIMEOUT
    assert observation.result.termination_confirmed is False
    assert observation.result.indeterminate is True
    assert observation.result.retry_count == 0
    assert calls == 1
    assert max_active == 1
    assert effects == []

    release.set()
    assert finished.wait(1)
    assert effects == ["published"]
    assert calls == 1


def test_confirmed_read_only_timeout_retries_with_stable_logical_key() -> None:
    contexts: list[tuple[str, str, int]] = []

    def execute(_arguments: dict[str, object]) -> dict[str, bool]:
        context = current_attempt_context()
        assert context is not None
        contexts.append(
            (context.attempt_id, context.idempotency_key, context.fencing_token)
        )
        if len(contexts) == 1:
            assert context.cancel_event.wait(1)
            return {"late": True}
        return {"ok": True}

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="sample.read",
            side_effect=ToolSideEffect.READ_ONLY,
            timeout_seconds=0.01,
            max_attempts=2,
        ),
        execute,
    )

    observation = ToolExecutor(registry).execute(
        ToolCall(tool_name="sample.read", call_id="stable-call"),
        ToolPolicy(
            require_explicit_allowlist=False,
            require_approval_for_side_effects=False,
            cancellation_grace_seconds=0.05,
        ),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output == {"ok": True}
    assert observation.result.retry_count == 1
    assert len(contexts) == 2
    assert contexts[0][0] != contexts[1][0]
    assert contexts[0][1] == contexts[1][1] == "tool:stable-call"
    assert [item[2] for item in contexts] == [1, 2]


def test_external_write_timeout_is_indeterminate_even_after_confirmed_exit() -> None:
    calls = 0
    effects: list[str] = []

    def execute(_arguments: dict[str, object]) -> dict[str, bool]:
        nonlocal calls
        calls += 1
        effects.append("accepted")
        context = current_attempt_context()
        assert context is not None
        assert context.cancel_event.wait(1)
        return {"accepted": True}

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="sample.publish",
            side_effect=ToolSideEffect.WRITES_EXTERNAL_STATE,
            timeout_seconds=0.01,
            max_attempts=3,
        ),
        execute,
    )

    observation = ToolExecutor(registry).execute(
        ToolCall(tool_name="sample.publish", call_id="publish-call"),
        ToolPolicy(
            require_explicit_allowlist=False,
            require_approval_for_side_effects=False,
            cancellation_grace_seconds=0.05,
        ),
    )

    assert observation.status == ToolStatus.TIMEOUT
    assert observation.result.termination_confirmed is True
    assert observation.result.indeterminate is True
    assert observation.result.error_envelope is not None
    assert observation.result.error_envelope["retryable"] is False
    assert calls == 1
    assert effects == ["accepted"]


class _BlockingMCPClient:
    def __init__(self) -> None:
        self.release = threading.Event()
        self.finished = threading.Event()

    def list_tools(self, _server: MCPServerConfig) -> list[dict[str, object]]:
        self.release.wait(1)
        self.finished.set()
        return []

    def call_tool(
        self,
        _server: MCPServerConfig,
        _remote_tool_name: str,
        _arguments: dict[str, object],
    ) -> object:
        return None


def test_mcp_timeout_does_not_report_future_cancellation_as_termination() -> None:
    client = _BlockingMCPClient()
    adapter = MCPToolAdapter(client)
    server = MCPServerConfig(
        server_id="blocking",
        name="Blocking",
        transport="in_memory",
        timeout_seconds=0.01,
    )

    with pytest.raises(ToolTimeoutError) as raised:
        adapter.list_tools(server)

    assert raised.value.termination_confirmed is False
    assert raised.value.indeterminate is True
    client.release.set()
    assert client.finished.wait(1)
