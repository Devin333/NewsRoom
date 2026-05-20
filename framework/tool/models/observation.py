from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.tool.governance.redaction import redact_sensitive_values
from framework.tool.models.artifact_ref import ArtifactRef
from framework.tool.models.call import ToolCall
from framework.tool.models.result import ToolResult
from framework.tool.models.status import ToolStatus


@dataclass(frozen=True)
class ToolObservation:
    call: ToolCall
    result: ToolResult
    elapsed_ms: float = 0.0
    content: str | None = None
    raw_result: ToolResult | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", dict(self.metadata or {}))
        if self.raw_result is None:
            object.__setattr__(self, "raw_result", self.result)
        if self.content is None:
            object.__setattr__(self, "content", self.to_message_text())

    @classmethod
    def from_result(cls, result: ToolResult) -> "ToolObservation":
        call = ToolCall(
            tool_name=result.tool_name,
            call_id=result.call_id or "",
            arguments={},
        )
        return cls(call=call, result=result)

    @property
    def tool_call_id(self) -> str:
        return self.call.call_id

    @property
    def tool_name(self) -> str:
        return self.call.tool_name

    @property
    def artifact_ref(self) -> ArtifactRef | None:
        return self.result.artifact_refs[0] if self.result.artifact_refs else None

    @property
    def sample(self) -> Any:
        if self.result.output is None:
            return None
        if isinstance(self.result.output, dict):
            return {
                key: value
                for key, value in list(redact_sensitive_values(self.result.output).items())[:3]
            }
        if isinstance(self.result.output, list):
            return redact_sensitive_values(self.result.output[:3])
        return redact_sensitive_values(self.result.output)

    @property
    def error_type(self) -> str | None:
        return self.result.error_type

    @property
    def status(self) -> ToolStatus:
        return self.result.status

    @property
    def summary(self) -> str:
        if self.result.output_summary:
            return self.result.output_summary
        if self.result.error_message:
            return f"Tool {self.call.tool_name} {self.status.value}: {self.result.error_message}"
        return f"Tool {self.call.tool_name} {self.status.value}"

    @property
    def highlights(self) -> list[str]:
        return _observation_highlights(self.result.output)

    @property
    def safe_for_llm(self) -> bool:
        return self.result.redacted

    def to_message_text(self) -> str:
        return self.summary

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_call_id": self.call.call_id,
            "tool_name": self.call.tool_name,
            "status": self.status.value,
            "summary": self.summary,
            "content": self.content,
            "artifact_ref": self.artifact_ref.to_dict() if self.artifact_ref else None,
            "sample": self.sample,
            "error_type": self.error_type,
            "highlights": self.highlights,
            "artifact_refs": [artifact_ref.to_dict() for artifact_ref in self.result.artifact_refs],
            "safe_for_llm": self.safe_for_llm,
            "call": self.call.to_dict(),
            "result": self.result.to_dict(),
            "elapsed_ms": self.elapsed_ms,
            "metadata": dict(self.metadata),
        }


def _observation_highlights(output: Any) -> list[str]:
    safe_output = redact_sensitive_values(output)
    if safe_output is None:
        return []
    if isinstance(safe_output, dict):
        return [
            f"{key}: {_preview_highlight_value(value)}"
            for key, value in list(safe_output.items())[:3]
        ]
    if isinstance(safe_output, list):
        return [f"{len(safe_output)} item(s)"]
    return [_preview_highlight_value(safe_output)]


def _preview_highlight_value(value: Any) -> str:
    if isinstance(value, dict):
        return f"{len(value)} field(s)"
    if isinstance(value, list):
        return f"{len(value)} item(s)"
    text = str(value)
    if len(text) > 120:
        return f"{text[:117]}..."
    return text
