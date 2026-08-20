from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterator

from framework.llm.models.response import LLMResponse
from framework.llm.models.stream import LLMStreamAccumulator, LLMStreamEvent
from framework.llm.models.usage import TokenUsage
from framework.shared.graph_identity import GraphExecutionIdentity


_TOOL_EVENT_TYPES = frozenset(
    {
        "tool_call_start",
        "tool_call_delta",
        "tool_call_complete",
    }
)


class LLMStreamProtocolError(ValueError):
    def __init__(
        self,
        reason: str,
        message: str,
        *,
        actual_execution_identity: GraphExecutionIdentity | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.actual_execution_identity = actual_execution_identity


@dataclass(frozen=True)
class LLMStreamCaptureResult:
    response: LLMResponse
    cacheable: bool
    reason: str
    protocol_reason: str | None = None


class LLMStreamCacheCapture:
    """Normalize and validate one provider stream without retaining raw events."""

    def __init__(
        self,
        *,
        expected_execution_identity: GraphExecutionIdentity | None = None,
    ) -> None:
        self._accumulator = LLMStreamAccumulator(
            expected_execution_identity=expected_execution_identity,
            require_expected_identity=True,
        )
        self._started = False
        self._completed = False
        self._tool_event_seen = False
        self._protocol_reason: str | None = None

    @property
    def completed(self) -> bool:
        return self._completed

    def add(self, raw_event: Any) -> LLMStreamEvent:
        event = LLMStreamEvent.from_any(raw_event)
        if self._completed:
            reason = (
                "duplicate_message_complete"
                if event.event_type == "message_complete"
                else "event_after_message_complete"
            )
            raise LLMStreamProtocolError(
                reason, "stream event received after message_complete"
            )

        if event.event_type == "message_start":
            if self._started:
                raise LLMStreamProtocolError(
                    "duplicate_message_start",
                    "message_start already received",
                )
            self._started = True
        elif not self._started:
            self._protocol_reason = (
                self._protocol_reason or "event_before_message_start"
            )

        if (
            event.event_type in _TOOL_EVENT_TYPES
            or event.tool_call is not None
            or event.tool_call_delta is not None
        ):
            self._tool_event_seen = True

        try:
            self._accumulator.add_event(event)
        except ValueError as exc:
            reason = (
                "stream_identity_mismatch"
                if "Graph identity" in str(exc)
                else self._protocol_reason or "invalid_stream_protocol"
            )
            raise LLMStreamProtocolError(
                reason,
                "provider stream protocol is invalid",
                actual_execution_identity=event.execution_identity,
            ) from exc
        if event.event_type == "message_complete":
            self._completed = True
        return event

    def finalize(self) -> LLMStreamCaptureResult:
        if not self._started:
            raise LLMStreamProtocolError(
                "missing_message_start",
                "provider stream did not emit message_start",
            )
        if not self._completed:
            raise LLMStreamProtocolError(
                "missing_message_complete",
                "provider stream did not emit message_complete",
            )
        response = self._accumulator.to_response()
        if self._protocol_reason is not None:
            return LLMStreamCaptureResult(
                response=response,
                cacheable=False,
                reason="invalid_stream_protocol",
                protocol_reason=self._protocol_reason,
            )
        if self._tool_event_seen or response.has_tool_calls():
            return LLMStreamCaptureResult(
                response=response,
                cacheable=False,
                reason="tool_event_present",
            )
        return LLMStreamCaptureResult(
            response=response,
            cacheable=True,
            reason="complete_text_stream",
        )


def iter_cached_response_events(
    response: LLMResponse,
    *,
    chunk_size: int,
) -> Iterator[LLMStreamEvent]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")

    completion_metadata = deepcopy(response.metadata)
    yield LLMStreamEvent(
        event_type="message_start",
        metadata={
            "provider": completion_metadata.get("llm_provider"),
            "model": completion_metadata.get("llm_model"),
            "deployment_id": completion_metadata.get("llm_deployment_id"),
            "cache_hit": True,
            "provider_call": False,
        },
        execution_identity=response.execution_identity,
    )

    content = response.content or ""
    for offset in range(0, len(content), chunk_size):
        yield LLMStreamEvent(
            event_type="text_delta",
            text_delta=content[offset : offset + chunk_size],
            execution_identity=response.execution_identity,
        )

    if _has_source_usage(response.usage):
        yield LLMStreamEvent(
            event_type="usage_delta",
            usage_delta=TokenUsage(),
            metadata={
                "source_usage": response.usage.to_dict(),
                "cache_hit": True,
                "provider_call": False,
            },
            execution_identity=response.execution_identity,
        )

    yield LLMStreamEvent(
        event_type="message_complete",
        structured_output=(
            deepcopy(response.structured_output)
            if response.structured_output is not None
            else None
        ),
        metadata=completion_metadata,
        execution_identity=response.execution_identity,
    )


def _has_source_usage(usage: TokenUsage) -> bool:
    return bool(
        usage.input_tokens
        or usage.output_tokens
        or usage.reasoning_tokens
        or usage.cached_input_tokens
        or usage.estimated_cost_usd is not None
    )
