from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class AgentMessageRecord:
    conversation_id: str
    role: str
    content: Any
    message_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: datetime = field(default_factory=_utc_now)
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
    def from_dict(cls, payload: dict[str, Any]) -> AgentMessageRecord:
        return cls(
            message_id=str(payload["message_id"]),
            conversation_id=str(payload["conversation_id"]),
            role=str(payload["role"]),
            content=payload.get("content"),
            created_at=_parse_datetime(str(payload["created_at"])),
            agent_id=_optional_str(payload.get("agent_id")),
            run_id=_optional_str(payload.get("run_id")),
            step_id=_optional_str(payload.get("step_id")),
            redacted=bool(payload.get("redacted", True)),
            metadata=dict(payload.get("metadata") or {}),
        )


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


@dataclass(frozen=True)
class ConversationCompactionRecord:
    conversation_id: str
    summary: str
    original_message_count: int
    compacted_message_count: int
    retained_message_count: int
    marker_message_id: str
    compacted_until_message_id: str | None = None
    created_at: datetime = field(default_factory=_utc_now)
    redacted: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "summary": self.summary,
            "original_message_count": self.original_message_count,
            "compacted_message_count": self.compacted_message_count,
            "retained_message_count": self.retained_message_count,
            "marker_message_id": self.marker_message_id,
            "compacted_until_message_id": self.compacted_until_message_id,
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "redacted": self.redacted,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ConversationCompactionRecord:
        return cls(
            conversation_id=str(payload["conversation_id"]),
            summary=str(payload.get("summary") or ""),
            original_message_count=int(payload.get("original_message_count") or 0),
            compacted_message_count=int(payload.get("compacted_message_count") or 0),
            retained_message_count=int(payload.get("retained_message_count") or 0),
            marker_message_id=str(payload["marker_message_id"]),
            compacted_until_message_id=_optional_str(payload.get("compacted_until_message_id")),
            created_at=_parse_datetime(str(payload["created_at"])),
            redacted=bool(payload.get("redacted", True)),
            metadata=dict(payload.get("metadata") or {}),
        )
