from __future__ import annotations

from typing import Any

from framework.events import (
    W3CSpanContext,
    current_trace_context,
    is_valid_span_id,
    is_valid_trace_id,
    trace_context_scope,
)
from interfaces.mcp.stdio_server import handle_jsonrpc_request


REMOTE_TRACE_ID = "1" * 32
REMOTE_SPAN_ID = "2" * 16


def test_mcp_meta_creates_scoped_child_without_entering_tool_arguments() -> None:
    service = _TraceCapturingMCPService()
    outer = W3CSpanContext.root()

    with trace_context_scope(outer):
        response = handle_jsonrpc_request(
            {
                "jsonrpc": "2.0",
                "id": "trace-call",
                "method": "tools/call",
                "params": {
                    "name": "news.echo",
                    "arguments": {"message": "hello"},
                    "_meta": {
                        "traceparent": (
                            f"00-{REMOTE_TRACE_ID}-{REMOTE_SPAN_ID}-01"
                        ),
                    },
                },
            },
            service=service,
        )
        assert current_trace_context() is outer

    assert current_trace_context() is None
    assert service.calls == [("news.echo", {"message": "hello"})]
    context = service.contexts[0]
    assert isinstance(context, W3CSpanContext)
    assert context.trace_id == REMOTE_TRACE_ID
    assert context.parent_span_id == REMOTE_SPAN_ID
    assert is_valid_span_id(context.span_id)
    assert "_meta" not in repr(response)
    assert "traceparent" not in repr(response)


def test_mcp_malformed_trace_and_business_baggage_are_not_trusted() -> None:
    service = _TraceCapturingMCPService()

    response = handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": "malformed-trace",
            "method": "tools/call",
            "params": {
                "name": "news.echo",
                "arguments": {},
                "_meta": {
                    "traceparent": "malformed",
                    "baggage": "run_id=attacker-selected",
                },
            },
        },
        service=service,
    )

    context = service.contexts[0]
    assert isinstance(context, W3CSpanContext)
    assert is_valid_trace_id(context.trace_id)
    assert context.trace_id != REMOTE_TRACE_ID
    assert service.calls == [("news.echo", {})]
    assert "attacker-selected" not in repr(response)
    assert current_trace_context() is None


class _TraceCapturingMCPService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.contexts: list[W3CSpanContext | None] = []

    def call_tool(self, tool_name: str, arguments: dict[str, Any]):
        self.calls.append((tool_name, dict(arguments)))
        context = current_trace_context()
        self.contexts.append(
            context if isinstance(context, W3CSpanContext) else None
        )
        return _ToolResult(tool_name)


class _ToolResult:
    def __init__(self, tool_name: str) -> None:
        self.tool_name = tool_name

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "success": True,
            "data": {"ok": True},
            "error_type": None,
            "error_message": None,
        }
