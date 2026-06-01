"""Generic shared session models for framework-level agent collaboration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class AgentSessionRef:
    """Reference values that identify one shared agent session boundary."""

    session_id: str
    run_id: str | None = None
    workflow_id: str | None = None
    parent_agent_id: str | None = None
    task_id: str | None = None

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
    summary: str | None = None
    confidence: float | None = None
    refs: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    created_at: str | None = None


@dataclass(frozen=True)
class AgentSessionContext:
    """Assembled prompt context for a shared agent session."""

    session_id: str
    items: tuple[AgentSessionItem, ...]
    context_text: str
    char_count: int
