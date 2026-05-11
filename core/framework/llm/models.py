from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Protocol

from core.framework.llm.redaction import redact_sensitive_values


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True)
class LLMRequest:
    messages: list[dict[str, str]]
    tools: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    response_format: str | dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    output_schema_name: str = "structured_output"

    def to_dict(self, *, redact: bool = True) -> dict[str, Any]:
        payload = {
            "messages": [dict(message) for message in self.messages],
            "tools": deepcopy(self.tools),
            "metadata": dict(self.metadata),
        }
        if self.response_format is not None:
            payload["response_format"] = deepcopy(self.response_format)
        if self.output_schema is not None:
            payload["output_schema"] = deepcopy(self.output_schema)
            payload["output_schema_name"] = self.output_schema_name
        if redact:
            return redact_sensitive_values(payload)
        return payload


@dataclass(frozen=True)
class LLMToolCall:
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    raw_arguments: str | None = None
    provider_tool_call_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, *, redact: bool = True) -> dict[str, Any]:
        payload = {
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "arguments": deepcopy(self.arguments),
            "raw_arguments": self.raw_arguments,
            "provider_tool_call_id": self.provider_tool_call_id,
            "metadata": dict(self.metadata),
        }
        if redact:
            return redact_sensitive_values(payload)
        return payload


@dataclass(frozen=True)
class LLMResponse:
    content: str
    usage: TokenUsage = field(default_factory=TokenUsage)
    metadata: dict[str, Any] = field(default_factory=dict)
    structured_output: dict[str, Any] | None = None
    tool_calls: list[LLMToolCall] = field(default_factory=list)

    def to_dict(self, *, redact: bool = True) -> dict[str, Any]:
        payload = {
            "content": self.content,
            "usage": self.usage.to_dict(),
            "metadata": dict(self.metadata),
            "structured_output": deepcopy(self.structured_output),
            "tool_calls": [tool_call.to_dict(redact=False) for tool_call in self.tool_calls],
        }
        if redact:
            return redact_sensitive_values(payload)
        return payload


class LLMClient(Protocol):
    def complete(self, request: LLMRequest) -> LLMResponse:
        ...
