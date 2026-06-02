"""Generic shared session models for framework-level agent collaboration."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping
from uuid import uuid4


class SessionVisibility(StrEnum):
    """Read visibility for one session item."""

    PUBLIC = "public"
    SHARED = "shared"
    PRIVATE = "private"
    FINAL = "final"


@dataclass(frozen=True)
class AgentSessionRef:
    """Reference values that identify one shared agent session boundary."""

    session_id: str
    run_id: str | None = None
    workflow_id: str | None = None
    parent_agent_id: str | None = None
    task_id: str | None = None
    tenant_id: str | None = None
    user_id: str | None = None

    def __post_init__(self) -> None:
        if not str(self.session_id or "").strip():
            raise ValueError("session_id is required")
        if not str(self.run_id or "").strip():
            object.__setattr__(self, "run_id", self.session_id)

    def to_refs(self) -> dict[str, str]:
        """Return only populated reference values."""

        return {
            key: value
            for key, value in {
                "session_id": self.session_id,
                "run_id": self.run_id,
                "workflow_id": self.workflow_id,
                "parent_agent_id": self.parent_agent_id,
                "task_id": self.task_id,
                "tenant_id": self.tenant_id,
                "user_id": self.user_id,
            }.items()
            if value
        }


@dataclass(frozen=True)
class AgentSessionItem:
    """Structured item written by an agent into a shared session."""

    session_id: str
    agent_id: str
    role: str
    content: Mapping[str, Any]
    item_id: str = field(default_factory=lambda: uuid4().hex)
    run_id: str = ""
    summary: str | None = None
    confidence: float | None = None
    visibility: SessionVisibility = SessionVisibility.SHARED
    refs: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None
    status: str = "active"
    version: int = 1

    def __post_init__(self) -> None:
        if not str(self.item_id or "").strip():
            object.__setattr__(self, "item_id", uuid4().hex)
        if not str(self.session_id or "").strip():
            raise ValueError("session_id is required")
        if not str(self.agent_id or "").strip():
            raise ValueError("agent_id is required")
        if not str(self.role or "").strip():
            raise ValueError("role is required")
        if not isinstance(self.content, Mapping):
            raise TypeError("content must be a Mapping")
        if not str(self.run_id or "").strip():
            object.__setattr__(self, "run_id", self.session_id)
        object.__setattr__(self, "visibility", SessionVisibility(str(self.visibility)))
        object.__setattr__(self, "refs", dict(self.refs or {}))
        object.__setattr__(self, "metadata", dict(self.metadata or {}))
        object.__setattr__(self, "status", str(self.status or "active"))
        object.__setattr__(self, "version", max(1, int(self.version or 1)))


@dataclass(frozen=True)
class AgentSessionEvent:
    """Append-only audit event for a shared agent session."""

    session_id: str
    run_id: str
    event_type: str
    event_id: str = field(default_factory=lambda: uuid4().hex)
    agent_id: str | None = None
    item_id: str | None = None
    role: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    created_at: str | None = None

    def __post_init__(self) -> None:
        if not str(self.event_id or "").strip():
            object.__setattr__(self, "event_id", uuid4().hex)
        if not str(self.session_id or "").strip():
            raise ValueError("session_id is required")
        if not str(self.event_type or "").strip():
            raise ValueError("event_type is required")
        if not str(self.run_id or "").strip():
            object.__setattr__(self, "run_id", self.session_id)
        object.__setattr__(self, "payload", dict(self.payload or {}))


@dataclass(frozen=True)
class AgentSessionSnapshot:
    """Compacted session state for long-running shared agent sessions."""

    session_id: str
    run_id: str
    summary: str
    role_summaries: Mapping[str, Any]
    final_items: tuple[str, ...]
    source_event_ids: tuple[str, ...]
    snapshot_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: str | None = None

    def __post_init__(self) -> None:
        if not str(self.snapshot_id or "").strip():
            object.__setattr__(self, "snapshot_id", uuid4().hex)
        if not str(self.session_id or "").strip():
            raise ValueError("session_id is required")
        if not str(self.run_id or "").strip():
            object.__setattr__(self, "run_id", self.session_id)
        object.__setattr__(self, "role_summaries", dict(self.role_summaries or {}))
        object.__setattr__(self, "final_items", tuple(str(item) for item in self.final_items))
        object.__setattr__(self, "source_event_ids", tuple(str(item) for item in self.source_event_ids))


@dataclass(frozen=True)
class AgentSessionContext:
    """Assembled prompt context for a shared agent session."""

    session_id: str
    items: tuple[AgentSessionItem, ...]
    context_text: str
    char_count: int
    snapshot: AgentSessionSnapshot | None = None
