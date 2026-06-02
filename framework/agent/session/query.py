"""Query model for reading shared agent session items."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from framework.agent.session.models import SessionVisibility


@dataclass(frozen=True)
class AgentSessionQuery:
    """Structured query boundary for session item reads."""

    session_id: str
    roles: tuple[str, ...] = ()
    agent_ids: tuple[str, ...] = ()
    statuses: tuple[str, ...] = ("active", "final")
    visibility: tuple[SessionVisibility, ...] = (
        SessionVisibility.PUBLIC,
        SessionVisibility.SHARED,
        SessionVisibility.FINAL,
    )
    refs: Mapping[str, Any] = field(default_factory=dict)
    limit: int | None = None
    include_content: bool = True
    include_private: bool = False

    def __post_init__(self) -> None:
        if not str(self.session_id or "").strip():
            raise ValueError("session_id is required")
        object.__setattr__(self, "roles", tuple(str(item) for item in self.roles))
        object.__setattr__(self, "agent_ids", tuple(str(item) for item in self.agent_ids))
        object.__setattr__(self, "statuses", tuple(str(item) for item in self.statuses))
        object.__setattr__(self, "visibility", tuple(SessionVisibility(str(item)) for item in self.visibility))
        object.__setattr__(self, "refs", dict(self.refs or {}))
