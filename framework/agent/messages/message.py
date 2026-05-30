from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from enum import Enum
from typing import Any
from uuid import uuid4


def utc_now() -> datetime:
    return datetime.now(UTC)


class AgentMessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    JUDGE = "judge"
    DIAGNOSTIC = "diagnostic"


@dataclass(frozen=True)
class AgentMessage:
    role: AgentMessageRole | str
    content: Any
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role.value if isinstance(self.role, AgentMessageRole) else str(self.role),
            "content": self.content,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AgentMessage":
        return cls(
            role=str(payload.get("role") or "user"),
            content=payload.get("content"),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class AgentMessageRecord:
    conversation_id: str
    role: str
    content: Any
    message_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: datetime = field(default_factory=utc_now)
    agent_id: str | None = None
    run_id: str | None = None
    step_id: str | None = None
    redacted: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "conversation_id": self.conversation_id,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "agent_id": self.agent_id,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "redacted": self.redacted,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AgentMessageRecord":
        return cls(
            message_id=str(payload["message_id"]),
            conversation_id=str(payload["conversation_id"]),
            role=str(payload["role"]),
            content=payload.get("content"),
            created_at=parse_datetime(str(payload["created_at"])),
            agent_id=optional_str(payload.get("agent_id")),
            run_id=optional_str(payload.get("run_id")),
            step_id=optional_str(payload.get("step_id")),
            redacted=bool(payload.get("redacted", True)),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class ConversationCursor:
    conversation_id: str
    message_offset: int
    message_id: str | None = None
    run_id: str | None = None
    step_id: str | None = None
    workflow_checkpoint_id: str | None = None
    updated_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "message_offset": self.message_offset,
            "message_id": self.message_id,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "workflow_checkpoint_id": self.workflow_checkpoint_id,
            "updated_at": self.updated_at.isoformat().replace("+00:00", "Z"),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ConversationCursor":
        return cls(
            conversation_id=str(payload["conversation_id"]),
            message_offset=int(payload.get("message_offset", 0)),
            message_id=optional_str(payload.get("message_id")),
            run_id=optional_str(payload.get("run_id")),
            step_id=optional_str(payload.get("step_id")),
            workflow_checkpoint_id=optional_str(payload.get("workflow_checkpoint_id")),
            updated_at=parse_datetime(str(payload["updated_at"])),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class AgentIterationCheckpoint:
    conversation_id: str
    agent_id: str
    iteration: int
    status: str
    stop_reason: str | None = None
    run_id: str | None = None
    step_id: str | None = None
    workflow_checkpoint_id: str | None = None
    message_id: str | None = None
    trace_summary: dict[str, Any] = field(default_factory=dict)
    diagnostics_summary: dict[str, Any] = field(default_factory=dict)
    last_tool_observation: dict[str, Any] | None = None
    llm_call_artifact_ids: list[str] = field(default_factory=list)
    updated_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "agent_id": self.agent_id,
            "iteration": self.iteration,
            "status": self.status,
            "stop_reason": self.stop_reason,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "workflow_checkpoint_id": self.workflow_checkpoint_id,
            "message_id": self.message_id,
            "trace_summary": dict(self.trace_summary),
            "diagnostics_summary": dict(self.diagnostics_summary),
            "last_tool_observation": dict(self.last_tool_observation) if self.last_tool_observation is not None else None,
            "llm_call_artifact_ids": list(self.llm_call_artifact_ids),
            "updated_at": self.updated_at.isoformat().replace("+00:00", "Z"),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AgentIterationCheckpoint":
        return cls(
            conversation_id=str(payload["conversation_id"]),
            agent_id=str(payload["agent_id"]),
            iteration=int(payload.get("iteration", 0)),
            status=str(payload["status"]),
            stop_reason=optional_str(payload.get("stop_reason")),
            run_id=optional_str(payload.get("run_id")),
            step_id=optional_str(payload.get("step_id")),
            workflow_checkpoint_id=optional_str(payload.get("workflow_checkpoint_id")),
            message_id=optional_str(payload.get("message_id")),
            trace_summary=dict(payload.get("trace_summary") or {}),
            diagnostics_summary=dict(payload.get("diagnostics_summary") or {}),
            last_tool_observation=dict(payload["last_tool_observation"]) if isinstance(payload.get("last_tool_observation"), dict) else None,
            llm_call_artifact_ids=[str(item) for item in payload.get("llm_call_artifact_ids") or []],
            updated_at=parse_datetime(str(payload["updated_at"])),
            metadata=dict(payload.get("metadata") or {}),
        )


def parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
