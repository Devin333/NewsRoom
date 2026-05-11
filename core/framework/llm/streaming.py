from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.framework.llm.models import LLMResponse, LLMToolCall, TokenUsage
from core.framework.llm.redaction import redact_sensitive_values


STREAM_EVENT_TYPES = {
    "message_start",
    "text_delta",
    "tool_call_complete",
    "usage_delta",
    "message_complete",
    "error",
}


@dataclass(frozen=True)
class LLMStreamEvent:
    event_type: str
    text_delta: str | None = None
    tool_call: LLMToolCall | None = None
    usage_delta: TokenUsage | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.event_type not in STREAM_EVENT_TYPES:
            raise ValueError(f"unsupported LLM stream event type: {self.event_type}")

    def to_dict(self, *, redact: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "event_type": self.event_type,
            "text_delta": self.text_delta,
            "tool_call": self.tool_call.to_dict(redact=False) if self.tool_call else None,
            "usage_delta": self.usage_delta.to_dict() if self.usage_delta else None,
            "metadata": dict(self.metadata),
        }
        if redact:
            return redact_sensitive_values(payload)
        return payload


class LLMStreamAccumulator:
    def __init__(self, *, metadata: dict[str, Any] | None = None) -> None:
        self._text_parts: list[str] = []
        self._tool_calls: list[LLMToolCall] = []
        self._usage = TokenUsage()
        self._metadata = dict(metadata or {})

    def add_event(self, event: LLMStreamEvent) -> None:
        if event.event_type == "text_delta" and event.text_delta:
            self._text_parts.append(event.text_delta)
        elif event.event_type == "tool_call_complete" and event.tool_call:
            self._tool_calls.append(event.tool_call)
        elif event.event_type == "usage_delta" and event.usage_delta:
            self._usage = TokenUsage(
                input_tokens=self._usage.input_tokens + event.usage_delta.input_tokens,
                output_tokens=self._usage.output_tokens + event.usage_delta.output_tokens,
            )
        elif event.event_type == "message_complete":
            self._metadata.update(event.metadata)
        elif event.event_type == "error":
            self._metadata.update({"stream_error": event.metadata})

    def to_response(self) -> LLMResponse:
        return LLMResponse(
            content="".join(self._text_parts),
            usage=self._usage,
            metadata=dict(self._metadata),
            tool_calls=list(self._tool_calls),
        )
