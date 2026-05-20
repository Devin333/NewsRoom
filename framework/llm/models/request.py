from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, cast

from framework.llm.models.message import LLMMessage
from framework.llm.redaction.redactor import redact_sensitive_values


@dataclass(frozen=True)
class LLMRequest:
    messages: list[dict[str, Any] | LLMMessage]
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    tools: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    response_format: str | dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    output_schema_name: str = "structured_output"

    def __post_init__(self) -> None:
        object.__setattr__(self, "messages", [_message_to_dict(message) for message in self.messages])

    def estimated_prompt_text(self) -> str:
        return "\n".join(str(message.get("content") or "") for message in self._message_dicts())

    def to_dict(self, *, redact: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "messages": [dict(message) for message in self._message_dicts()],
            "tools": deepcopy(self.tools),
            "metadata": dict(self.metadata),
        }
        if self.model is not None:
            payload["model"] = self.model
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens
        if self.response_format is not None:
            payload["response_format"] = deepcopy(self.response_format)
        if self.output_schema is not None:
            payload["output_schema"] = deepcopy(self.output_schema)
            payload["output_schema_name"] = self.output_schema_name
        if redact:
            return redact_sensitive_values(payload)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> LLMRequest:
        return cls(
            messages=list(payload.get("messages") or []),
            model=payload.get("model"),
            temperature=(
                float(payload["temperature"]) if payload.get("temperature") is not None else None
            ),
            max_tokens=int(payload["max_tokens"]) if payload.get("max_tokens") is not None else None,
            tools=list(payload.get("tools") or []),
            metadata=dict(payload.get("metadata") or {}),
            response_format=deepcopy(payload.get("response_format")),
            output_schema=deepcopy(payload.get("output_schema")),
            output_schema_name=str(payload.get("output_schema_name") or "structured_output"),
        )

    def _message_dicts(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], self.messages)


def _message_to_dict(message: dict[str, Any] | LLMMessage) -> dict[str, Any]:
    if isinstance(message, LLMMessage):
        return message.to_dict()
    return dict(message)

