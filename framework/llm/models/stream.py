from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from framework.llm.models.tool_call import LLMToolCall
from framework.llm.models.usage import TokenUsage
from framework.llm.redaction.redactor import redact_sensitive_values


STREAM_EVENT_TYPES = {
    "message_start",
    "text_delta",
    "tool_call_start",
    "tool_call_delta",
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
    tool_call_delta: dict[str, Any] | None = None
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
            "tool_call_delta": dict(self.tool_call_delta or {}),
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
        self._tool_call_deltas: dict[str, dict[str, Any]] = {}
        self._usage = TokenUsage()
        self._metadata = dict(metadata or {})
        self._started = False
        self._completed = False
        self._errored = False

    def add(self, event: LLMStreamEvent) -> None:
        self.add_event(event)

    def add_event(self, event: LLMStreamEvent) -> None:
        if self._completed:
            raise ValueError("cannot add stream events after message_complete")
        if self._errored:
            raise ValueError("cannot add stream events after error")
        if event.event_type == "message_start":
            if self._started:
                raise ValueError("message_start already received")
            self._started = True
        elif event.event_type == "text_delta" and event.text_delta:
            self._require_started(event)
            self._text_parts.append(event.text_delta)
        elif event.event_type == "tool_call_start":
            self._require_started(event)
            delta = dict(event.tool_call_delta or event.metadata)
            tool_call_id = _tool_call_delta_id(delta)
            self._tool_call_deltas[tool_call_id] = {
                "tool_call_id": tool_call_id,
                "tool_name": str(delta.get("tool_name") or delta.get("name") or ""),
                "arguments": str(delta.get("arguments") or ""),
                "provider_tool_call_id": delta.get("provider_tool_call_id") or delta.get("id"),
            }
        elif event.event_type == "tool_call_delta":
            self._require_started(event)
            delta = dict(event.tool_call_delta or event.metadata)
            tool_call_id = _tool_call_delta_id(delta)
            current = self._tool_call_deltas.setdefault(
                tool_call_id,
                {
                    "tool_call_id": tool_call_id,
                    "tool_name": "",
                    "arguments": "",
                    "provider_tool_call_id": delta.get("provider_tool_call_id") or delta.get("id"),
                },
            )
            if delta.get("tool_name") or delta.get("name"):
                current["tool_name"] = (
                    f"{current.get('tool_name', '')}{delta.get('tool_name') or delta.get('name')}"
                )
            if delta.get("arguments"):
                current["arguments"] = f"{current.get('arguments', '')}{delta.get('arguments')}"
        elif event.event_type == "tool_call_complete" and event.tool_call:
            self._require_started(event)
            self._tool_calls.append(event.tool_call)
        elif event.event_type == "usage_delta" and event.usage_delta:
            self._require_started(event)
            self._usage = TokenUsage(
                input_tokens=self._usage.input_tokens + event.usage_delta.input_tokens,
                output_tokens=self._usage.output_tokens + event.usage_delta.output_tokens,
                reasoning_tokens=self._usage.reasoning_tokens + event.usage_delta.reasoning_tokens,
                cached_input_tokens=(
                    self._usage.cached_input_tokens + event.usage_delta.cached_input_tokens
                ),
                estimated_cost_usd=_sum_optional_cost(
                    self._usage.estimated_cost_usd,
                    event.usage_delta.estimated_cost_usd,
                ),
            )
        elif event.event_type == "message_complete":
            self._require_started(event)
            self._complete_partial_tool_calls()
            self._metadata.update(event.metadata)
            self._completed = True
        elif event.event_type == "error":
            self._metadata.update({"stream_error": event.metadata})
            self._errored = True
            error_type = str(event.metadata.get("error_type") or "stream_interrupted")
            raise RuntimeError(f"LLM stream error: {error_type}")

    def to_response(self):
        from framework.llm.models.response import LLMResponse

        return LLMResponse(
            content="".join(self._text_parts),
            usage=self._usage,
            metadata=dict(self._metadata),
            tool_calls=list(self._tool_calls),
        )

    def _require_started(self, event: LLMStreamEvent) -> None:
        if not self._started:
            raise ValueError(f"{event.event_type} received before message_start")

    def _complete_partial_tool_calls(self) -> None:
        for raw in self._tool_call_deltas.values():
            tool_name = str(raw.get("tool_name") or "")
            if not tool_name:
                continue
            raw_arguments = str(raw.get("arguments") or "{}")
            try:
                arguments = json.loads(raw_arguments)
            except Exception as exc:
                raise ValueError("streaming tool call arguments are not valid JSON") from exc
            if not isinstance(arguments, dict):
                raise ValueError("streaming tool call arguments must be a JSON object")
            self._tool_calls.append(
                LLMToolCall(
                    tool_call_id=str(raw["tool_call_id"]),
                    tool_name=tool_name,
                    arguments=arguments,
                    raw_arguments=raw_arguments,
                    provider_tool_call_id=(
                        str(raw["provider_tool_call_id"])
                        if raw.get("provider_tool_call_id")
                        else None
                    ),
                )
            )
        self._tool_call_deltas.clear()


def _tool_call_delta_id(delta: dict[str, Any]) -> str:
    return str(
        delta.get("tool_call_id")
        or delta.get("provider_tool_call_id")
        or delta.get("id")
        or "tool_call_1"
    )


def _sum_optional_cost(left: float | None, right: float | None) -> float | None:
    if left is None and right is None:
        return None
    return round(float(left or 0.0) + float(right or 0.0), 12)

