from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

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

    def to_dict(self, *, redact: bool = True) -> dict[str, Any]:
        payload = {
            "messages": [dict(message) for message in self.messages],
            "tools": [dict(tool) for tool in self.tools],
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

    def to_dict(self, *, redact: bool = True) -> dict[str, Any]:
        payload = {
            "content": self.content,
            "usage": self.usage.to_dict(),
            "metadata": dict(self.metadata),
        }
        if redact:
            return redact_sensitive_values(payload)
        return payload
