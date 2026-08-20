from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from framework.llm.models.tool_call import LLMToolCall
from framework.llm.models.usage import TokenUsage
from framework.llm.redaction.redactor import redact_sensitive_values
from framework.shared.graph_identity import GraphExecutionIdentity


@dataclass(frozen=True)
class LLMResponse:
    content: str | None = ""
    usage: TokenUsage = field(default_factory=TokenUsage)
    metadata: dict[str, Any] = field(default_factory=dict)
    execution_identity: GraphExecutionIdentity | None = None
    structured_output: dict[str, Any] | None = None
    tool_calls: list[LLMToolCall] = field(default_factory=list)
    model: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "tool_calls",
            [LLMToolCall.from_dict(tool_call) for tool_call in self.tool_calls],
        )
        object.__setattr__(self, "usage", TokenUsage.from_any(self.usage))
        if self.execution_identity is not None and not isinstance(
            self.execution_identity, GraphExecutionIdentity
        ):
            object.__setattr__(
                self,
                "execution_identity",
                GraphExecutionIdentity.from_dict(self.execution_identity),
            )

    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    def to_dict(self, *, redact: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "content": self.content,
            "usage": self.usage.to_dict(),
            "metadata": dict(self.metadata),
            "structured_output": deepcopy(self.structured_output),
            "tool_calls": [tool_call.to_dict(redact=False) for tool_call in self.tool_calls],
        }
        if self.execution_identity is not None:
            payload["execution_identity"] = self.execution_identity.to_dict()
        if self.model is not None:
            payload["model"] = self.model
        if self.raw:
            payload["raw"] = deepcopy(self.raw)
        if redact:
            return redact_sensitive_values(payload)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> LLMResponse:
        return cls(
            content=payload.get("content"),
            usage=TokenUsage.from_dict(payload.get("usage")),
            metadata=dict(payload.get("metadata") or {}),
            execution_identity=(
                GraphExecutionIdentity.from_dict(payload["execution_identity"])
                if payload.get("execution_identity") is not None
                else None
            ),
            structured_output=deepcopy(payload.get("structured_output")),
            tool_calls=[
                LLMToolCall.from_dict(tool_call) for tool_call in payload.get("tool_calls") or []
            ],
            model=payload.get("model"),
            raw=dict(payload.get("raw") or {}),
        )

    @classmethod
    def from_any(cls, value: Any) -> LLMResponse:
        if isinstance(value, cls):
            return value
        if value is None:
            raise TypeError("LLM response is required")
        if isinstance(value, dict):
            return cls.from_dict(value)
        return cls(
            content=getattr(value, "content", ""),
            usage=TokenUsage.from_any(getattr(value, "usage", None)),
            metadata=dict(getattr(value, "metadata", {}) or {}),
            execution_identity=getattr(value, "execution_identity", None),
            structured_output=(
                dict(getattr(value, "structured_output"))
                if isinstance(getattr(value, "structured_output", None), dict)
                else None
            ),
            tool_calls=[
                LLMToolCall.from_dict(tool_call)
                for tool_call in getattr(value, "tool_calls", [])
            ],
            model=getattr(value, "model", None),
            raw=(
                dict(getattr(value, "raw"))
                if isinstance(getattr(value, "raw", None), dict)
                else {}
            ),
        )

