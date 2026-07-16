from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from framework.events import (
    EventTelemetry,
    TelemetryInstrumentationScope,
    TelemetryResource,
    TraceContext,
    W3CSpanContext,
    W3CTracePropagator,
    current_trace_context,
    default_event_telemetry,
    trace_context_scope,
)


class HTTPClientProtocol(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_seconds: float,
    ) -> Any: ...


class TraceAwareHTTPToolTransport:
    """ToolRuntime HTTP boundary with per-request W3C propagation."""

    def __init__(
        self,
        client: HTTPClientProtocol,
        *,
        trace_context: TraceContext | W3CSpanContext | None = None,
        trace_propagator: W3CTracePropagator | None = None,
        telemetry: EventTelemetry | None = None,
    ) -> None:
        self._client = client
        self._trace_context = trace_context
        self._trace_propagator = trace_propagator or W3CTracePropagator()
        self._telemetry = telemetry or default_event_telemetry(
            resource=TelemetryResource(service_name="newsroom-tool-runtime"),
            scope=TelemetryInstrumentationScope(name="framework.tool", version="1"),
        )

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        timeout_seconds: float = 30.0,
    ) -> Any:
        if not isinstance(method, str) or not method.strip():
            raise ValueError("HTTP method is required")
        if not isinstance(url, str) or not url.strip():
            raise ValueError("HTTP URL is required")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        outbound_context = self._outbound_context()
        outbound_headers = self._trace_propagator.inject(
            outbound_context,
            headers or {},
        )
        with trace_context_scope(outbound_context), self._telemetry.start_span(
            "newsroom.tool.http",
            attributes={
                "newsroom.component": "tool",
                "newsroom.operation": "request",
                "newsroom.transport": "http",
            },
        ):
            return self._client.request(
                method.strip().upper(),
                url,
                headers=outbound_headers,
                body=body,
                timeout_seconds=float(timeout_seconds),
            )

    def _outbound_context(self) -> W3CSpanContext:
        context = self._trace_context or current_trace_context()
        if isinstance(context, TraceContext):
            span_context = W3CSpanContext.from_trace_context(context)
        else:
            span_context = context
        return (span_context or W3CSpanContext.root()).child()


__all__ = [
    "HTTPClientProtocol",
    "TraceAwareHTTPToolTransport",
]
